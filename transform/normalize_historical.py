"""Normalización y limpieza del histórico de viajes.

Lee CSV crudos (esquema variable entre años), normaliza columnas, construye las
marcas de tiempo con un parser explícito, clasifica los rechazos por causa (no
los borra en silencio) y carga ``trips_raw``, ``trips_clean`` y
``trip_rejections`` en DuckDB. Reporta totales y rechazos por motivo/archivo.

Uso:
    python -m transform.normalize_historical                 # todos los descargados
    python -m transform.normalize_historical --file ruta.csv # un archivo
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from common.config import get_settings
from common.db import finish_run, get_connection, new_run_id, start_run, utcnow_naive
from common.logging_utils import get_logger
from transform.parsing import (
    CANONICAL_COLUMNS,
    clean_station_id,
    coerce_age,
    normalize_columns,
    parse_datetime_series,
)

logger = get_logger(__name__)

# --- Motivos de rechazo (constantes estables para reportes y pruebas) ---
REASON_INVALID_DATETIME = "fecha_hora_invalida"
REASON_MISSING_ORIGIN = "estacion_origen_ausente"
REASON_MISSING_DEST = "estacion_destino_ausente"
REASON_ARRIVAL_NOT_AFTER = "arribo_no_posterior"
REASON_TOO_SHORT = "duracion_muy_corta"
REASON_TOO_LONG = "duracion_muy_larga"
REASON_MISSING_BIKE = "bici_ausente"
REASON_DUPLICATE = "duplicado"

ALL_REASONS = [
    REASON_DUPLICATE,
    REASON_INVALID_DATETIME,
    REASON_MISSING_ORIGIN,
    REASON_MISSING_DEST,
    REASON_ARRIVAL_NOT_AFTER,
    REASON_TOO_SHORT,
    REASON_TOO_LONG,
    REASON_MISSING_BIKE,
]

_KEY_COLS = [
    "bici",
    "ciclo_estacion_retiro",
    "fecha_retiro",
    "hora_retiro",
    "ciclo_estacion_arribo",
    "fecha_arribo",
    "hora_arribo",
]


def read_raw_csv(path: str | Path) -> pd.DataFrame:
    """Lee un CSV crudo como texto, tolerando codificaciones utf-8/latin-1."""
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, keep_default_na=False)
        except UnicodeDecodeError:
            continue
    # Último recurso: reemplaza caracteres inválidos.
    return pd.read_csv(path, dtype=str, encoding="utf-8", encoding_errors="replace",
                       keep_default_na=False)


def _row_hashes(df: pd.DataFrame, source_file: str) -> pd.Series:
    """Hash estable por fila (para trip_id y trazabilidad)."""
    key = df[_KEY_COLS].astype("string").fillna("")
    base = pd.util.hash_pandas_object(key, index=False).astype("uint64")
    prefix = abs(hash(source_file)) % (10**8)
    return (base.astype("string") + f"_{prefix}")


def clean_dataframe(
    raw: pd.DataFrame,
    source_file: str,
    run_id: str,
    cfg: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Limpia un DataFrame crudo. Devuelve (trips_clean, trip_rejections, reporte).

    No elimina filas en silencio: cada fila inválida queda en trip_rejections con
    su motivo. Las marcas de tiempo se interpretan en hora local.
    """
    settings = get_settings()
    cfg = cfg or settings.get("cleaning", default={})
    date_formats = cfg.get("date_formats", ["%d/%m/%Y", "%Y-%m-%d"])
    time_formats = cfg.get("time_formats", ["%H:%M:%S", "%H:%M"])
    min_dur = float(cfg.get("min_duration_minutes", 1))
    max_dur = float(cfg.get("max_duration_minutes", 240))

    df = normalize_columns(raw)
    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df.reset_index(drop=True)

    row_hash = _row_hashes(df, source_file)

    retiro = parse_datetime_series(df["fecha_retiro"], df["hora_retiro"], date_formats, time_formats)
    arribo = parse_datetime_series(df["fecha_arribo"], df["hora_arribo"], date_formats, time_formats)
    origin = clean_station_id(df["ciclo_estacion_retiro"])
    dest = clean_station_id(df["ciclo_estacion_arribo"])
    bike = clean_station_id(df["bici"])
    duration_min = (arribo - retiro).dt.total_seconds() / 60.0

    # Clasificación de rechazos por prioridad (una causa por fila).
    reason = pd.Series(pd.NA, index=df.index, dtype="object")
    dup = df.duplicated(subset=_KEY_COLS, keep="first")
    reason = reason.mask(reason.isna() & dup, REASON_DUPLICATE)
    reason = reason.mask(reason.isna() & (retiro.isna() | arribo.isna()), REASON_INVALID_DATETIME)
    reason = reason.mask(reason.isna() & origin.isna(), REASON_MISSING_ORIGIN)
    reason = reason.mask(reason.isna() & dest.isna(), REASON_MISSING_DEST)
    reason = reason.mask(reason.isna() & (arribo <= retiro), REASON_ARRIVAL_NOT_AFTER)
    reason = reason.mask(reason.isna() & (duration_min < min_dur), REASON_TOO_SHORT)
    reason = reason.mask(reason.isna() & (duration_min > max_dur), REASON_TOO_LONG)
    reason = reason.mask(reason.isna() & bike.isna(), REASON_MISSING_BIKE)

    valid_mask = reason.isna()

    clean = pd.DataFrame(
        {
            "trip_id": row_hash[valid_mask],
            "bike_id": bike[valid_mask],
            "origin_station_id": origin[valid_mask],
            "dest_station_id": dest[valid_mask],
            "retiro_ts": retiro[valid_mask],
            "arribo_ts": arribo[valid_mask],
            "duration_min": duration_min[valid_mask],
            "genero": df.loc[valid_mask, "genero_usuario"],
            "edad": coerce_age(df.loc[valid_mask, "edad_usuario"]),
            "source_file": source_file,
            "run_id": run_id,
        }
    )
    # Elimina IDs de viaje duplicados que pudieran colisionar (defensivo).
    clean = clean.drop_duplicates(subset=["trip_id"]).reset_index(drop=True)

    rej_mask = ~valid_mask
    rejections = pd.DataFrame(
        {
            "row_hash": row_hash[rej_mask],
            "source_file": source_file,
            "run_id": run_id,
            "reason": reason[rej_mask],
            "detail": pd.NA,
            "retiro_raw": (df.loc[rej_mask, "fecha_retiro"].astype("string") + " "
                           + df.loc[rej_mask, "hora_retiro"].astype("string")),
            "arribo_raw": (df.loc[rej_mask, "fecha_arribo"].astype("string") + " "
                           + df.loc[rej_mask, "hora_arribo"].astype("string")),
            "rejected_at_utc": utcnow_naive(),
        }
    ).reset_index(drop=True)

    total = len(df)
    n_valid = len(clean)
    n_rej = total - n_valid
    by_reason = reason[rej_mask].value_counts().to_dict()
    report = {
        "source_file": source_file,
        "total": total,
        "validas": n_valid,
        "rechazadas": n_rej,
        "pct_rechazado": round(100 * n_rej / total, 3) if total else 0.0,
        "por_motivo": {r: int(by_reason.get(r, 0)) for r in ALL_REASONS},
    }
    return clean, rejections, report


def _persist(con, raw: pd.DataFrame, clean: pd.DataFrame, rejections: pd.DataFrame,
             source_file: str, run_id: str) -> None:
    """Escribe trips_raw/clean/rejections en DuckDB."""
    # trips_raw: columnas canónicas como texto.
    raw_norm = normalize_columns(raw)
    for col in CANONICAL_COLUMNS:
        if col not in raw_norm.columns:
            raw_norm[col] = pd.NA
    raw_out = raw_norm[CANONICAL_COLUMNS].copy()
    raw_out["row_hash"] = _row_hashes(normalize_columns(raw), source_file).values
    raw_out["source_file"] = source_file
    raw_out["run_id"] = run_id
    raw_out["ingested_at_utc"] = utcnow_naive()
    con.register("tmp_raw", raw_out)
    con.execute(
        """
        INSERT INTO trips_raw
            (row_hash, source_file, run_id, ingested_at_utc, genero_usuario, edad_usuario,
             bici, ciclo_estacion_retiro, fecha_retiro, hora_retiro,
             ciclo_estacion_arribo, fecha_arribo, hora_arribo)
        SELECT row_hash, source_file, run_id, ingested_at_utc, genero_usuario, edad_usuario,
               bici, ciclo_estacion_retiro, fecha_retiro, hora_retiro,
               ciclo_estacion_arribo, fecha_arribo, hora_arribo
        FROM tmp_raw
        """
    )
    con.unregister("tmp_raw")

    con.register("tmp_clean", clean)
    con.execute(
        "INSERT INTO trips_clean SELECT * FROM tmp_clean "
        "WHERE trip_id NOT IN (SELECT trip_id FROM trips_clean)"
    )
    con.unregister("tmp_clean")

    con.register("tmp_rej", rejections)
    con.execute("INSERT INTO trip_rejections SELECT * FROM tmp_rej")
    con.unregister("tmp_rej")


def _downloaded_files() -> list[str]:
    """Rutas locales de archivos con estado 'downloaded' en el manifiesto."""
    settings = get_settings()
    manifest = settings.path("manifests") / "ecobici_historico.csv"
    if not manifest.exists():
        return []
    df = pd.read_csv(manifest)
    ok = df[df["download_status"] == "downloaded"].dropna(subset=["local_path"])
    return [p for p in ok["local_path"].tolist() if Path(p).exists()]


def normalize_files(files: list[str]) -> dict[str, Any]:
    """Normaliza una lista de archivos y persiste. Devuelve reporte agregado."""
    con = get_connection()
    run_id = new_run_id("normalize")
    start_run(con, run_id, "normalize", source=";".join(Path(f).name for f in files) or None)
    reports: list[dict[str, Any]] = []
    total_valid = 0
    try:
        for f in files:
            raw = read_raw_csv(f)
            clean, rejections, report = clean_dataframe(raw, Path(f).name, run_id)
            _persist(con, raw, clean, rejections, Path(f).name, run_id)
            reports.append(report)
            total_valid += report["validas"]
            logger.info(
                "%s: total=%d válidas=%d rechazadas=%d (%.2f%%)",
                report["source_file"], report["total"], report["validas"],
                report["rechazadas"], report["pct_rechazado"],
            )
        finish_run(con, run_id, "ok", rows_ingested=total_valid)
    except Exception as exc:  # noqa: BLE001
        finish_run(con, run_id, "error", notes=str(exc))
        con.close()
        raise

    # Reporte consolidado a reports/rejection_report.csv
    if reports:
        rep_df = pd.DataFrame(
            [
                {"source_file": r["source_file"], "total": r["total"], "validas": r["validas"],
                 "rechazadas": r["rechazadas"], "pct_rechazado": r["pct_rechazado"],
                 **{f"motivo_{k}": v for k, v in r["por_motivo"].items()}}
                for r in reports
            ]
        )
        out = get_settings().path("reports") / "rejection_report.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        rep_df.to_csv(out, index=False)
        logger.info("Reporte de rechazos escrito en %s", out)
    con.close()
    return {"run_id": run_id, "archivos": len(files), "reportes": reports}


def main() -> int:
    parser = argparse.ArgumentParser(description="Normaliza el histórico de ECOBICI.")
    parser.add_argument("--file", type=str, default=None, help="Ruta a un CSV específico.")
    args = parser.parse_args()
    files = [args.file] if args.file else _downloaded_files()
    if not files:
        logger.warning("No hay archivos descargados para normalizar. Ejecuta download_historical.")
        return 0
    result = normalize_files(files)
    logger.info("Normalización completa: %d archivos, run=%s", result["archivos"], result["run_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
