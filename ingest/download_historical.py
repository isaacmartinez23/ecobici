"""Descargador del histórico de viajes de ECOBICI.

Lee el manifiesto producido por ``scrape_historical_urls`` y descarga los
archivos seleccionados a ``data/raw/``. Evita re-descargar archivos sin cambios
(compara checksum), soporta ZIP y CSV, registra tamaño/checksum/estado y permite
elegir un rango de meses.

Uso:
    python -m ingest.download_historical --latest 1
    python -m ingest.download_historical --from 2025-06 --to 2025-08
    python -m ingest.download_historical --months 2025-07,2025-08
    python -m ingest.download_historical --latest 1 --max-mb 200
"""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

import pandas as pd

from common.config import get_settings
from common.db import get_connection, utcnow_naive
from common.http import get
from common.logging_utils import get_logger

logger = get_logger(__name__)

MANIFEST_NAME = "ecobici_historico.csv"


def _manifest_path() -> Path:
    return get_settings().path("manifests") / MANIFEST_NAME


def load_manifest() -> pd.DataFrame:
    path = _manifest_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No existe el manifiesto {path}. Ejecuta primero scrape_historical_urls."
        )
    return pd.read_csv(path, dtype={"year": "Int64", "month": "Int64"})


def _period_key(year, month) -> int | None:
    if pd.isna(year) or pd.isna(month):
        return None
    return int(year) * 100 + int(month)


def select_files(
    df: pd.DataFrame,
    from_period: str | None = None,
    to_period: str | None = None,
    latest: int | None = None,
    months: list[str] | None = None,
) -> pd.DataFrame:
    """Filtra el manifiesto por rango de meses, meses explícitos o los N últimos."""
    df = df.copy()
    df["period_key"] = df.apply(lambda r: _period_key(r["year"], r["month"]), axis=1)

    if months:
        wanted = {int(m.replace("-", "")) for m in months}
        return df[df["period_key"].isin(wanted)]

    sel = df
    if from_period:
        sel = sel[sel["period_key"] >= int(from_period.replace("-", ""))]
    if to_period:
        sel = sel[sel["period_key"] <= int(to_period.replace("-", ""))]
    sel = sel.dropna(subset=["period_key"]).sort_values("period_key")
    if latest:
        sel = sel.tail(latest)
    return sel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest_dir: Path, max_bytes: int | None = None) -> dict:
    """Descarga un archivo en streaming. Devuelve dict con status/size/checksum/path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_name = Path(url.split("?")[0]).name
    dest = dest_dir / file_name
    resp = get(url, stream=True)
    total = 0
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if not chunk:
                continue
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"{file_name} excede el límite de {max_bytes/1e6:.0f} MB; omitido."
                )
            fh.write(chunk)
    checksum = _sha256(dest)
    local_path = str(dest)

    # Si es ZIP, extrae los CSV a data/raw y apunta local_path al primero.
    if zipfile.is_zipfile(dest):
        extracted = _extract_zip(dest, dest_dir)
        if extracted:
            local_path = str(extracted[0])

    return {
        "http_status": resp.status_code,
        "size_bytes": total,
        "checksum_sha256": checksum,
        "local_path": local_path,
    }


def _extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                target = dest_dir / Path(name).name
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                out.append(target)
    logger.info("ZIP %s -> %d CSV extraídos", zip_path.name, len(out))
    return out


def _save_manifest(df: pd.DataFrame) -> None:
    cols = [c for c in df.columns if c != "period_key"]
    df[cols].to_csv(_manifest_path(), index=False)


def _sync_status_to_duckdb(url: str, info: dict, status: str) -> None:
    con = get_connection()
    con.execute(
        """
        UPDATE historical_file_manifest
        SET download_status = ?, http_status = ?, size_bytes = ?,
            checksum_sha256 = ?, local_path = ?, last_downloaded_at_utc = ?
        WHERE url = ?
        """,
        [
            status,
            info.get("http_status"),
            info.get("size_bytes"),
            info.get("checksum_sha256"),
            info.get("local_path"),
            utcnow_naive(),
            url,
        ],
    )
    con.close()


def run_download(
    from_period: str | None = None,
    to_period: str | None = None,
    latest: int | None = None,
    months: list[str] | None = None,
    max_mb: float | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """Descarga los archivos seleccionados y actualiza el manifiesto."""
    settings = get_settings()
    raw_dir = settings.path("raw")
    manifest = load_manifest()
    # pandas 3.0 es estricto: aseguramos dtype object en columnas que mutamos con
    # valores string/None para no fallar al asignar sobre columnas todo-NaN.
    for col in (
        "download_status",
        "http_status",
        "size_bytes",
        "checksum_sha256",
        "local_path",
        "last_downloaded_at_utc",
    ):
        manifest[col] = manifest[col].astype(object)
    selection = select_files(manifest, from_period, to_period, latest, months)
    logger.info("Seleccionados %d archivos para descarga", len(selection))
    max_bytes = int(max_mb * 1e6) if max_mb else None

    for _idx, row in selection.iterrows():
        url = row["url"]
        existing = manifest.loc[manifest["url"] == url]
        already = (
            not force
            and not existing.empty
            and existing.iloc[0].get("download_status") == "downloaded"
            and pd.notna(existing.iloc[0].get("local_path"))
            and Path(str(existing.iloc[0]["local_path"])).exists()
        )
        if already:
            logger.info("Omitido (ya descargado): %s", row["file_name"])
            continue
        try:
            info = download_file(url, raw_dir, max_bytes=max_bytes)
            manifest.loc[manifest["url"] == url, "download_status"] = "downloaded"
            for k in ("http_status", "size_bytes", "checksum_sha256", "local_path"):
                manifest.loc[manifest["url"] == url, k] = info[k]
            manifest.loc[manifest["url"] == url, "last_downloaded_at_utc"] = utcnow_naive().isoformat()
            _sync_status_to_duckdb(url, info, "downloaded")
            logger.info(
                "Descargado %s (%.1f MB)", row["file_name"], info["size_bytes"] / 1e6
            )
        except Exception as exc:  # noqa: BLE001
            manifest.loc[manifest["url"] == url, "download_status"] = "failed"
            _sync_status_to_duckdb(url, {}, "failed")
            logger.error("Falló la descarga de %s: %s", row["file_name"], exc)

    _save_manifest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Descargador del histórico de ECOBICI.")
    parser.add_argument("--from", dest="from_period", type=str, default=None, help="YYYY-MM inicial")
    parser.add_argument("--to", dest="to_period", type=str, default=None, help="YYYY-MM final")
    parser.add_argument("--latest", type=int, default=None, help="Descarga los N meses más recientes")
    parser.add_argument("--months", type=str, default=None, help="Lista YYYY-MM separada por comas")
    parser.add_argument("--max-mb", type=float, default=None, help="Límite de tamaño por archivo (MB)")
    parser.add_argument("--force", action="store_true", help="Re-descarga aunque exista")
    args = parser.parse_args()

    months = args.months.split(",") if args.months else None
    if not any([args.from_period, args.to_period, args.latest, months]):
        parser.error("Especifica --from/--to, --latest o --months.")
    run_download(
        from_period=args.from_period,
        to_period=args.to_period,
        latest=args.latest,
        months=months,
        max_mb=args.max_mb,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
