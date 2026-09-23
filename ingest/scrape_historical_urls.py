"""Scraper de enlaces del histórico de viajes de ECOBICI.

No construye URLs con una fórmula: la carpeta de publicación puede diferir del
mes contenido en el archivo (ej. ``/wp-content/uploads/2026/02/2026-01.csv``).
En su lugar, extrae los enlaces reales de la página y deduce año/mes del nombre.

Uso:
    python -m ingest.scrape_historical_urls
    python -m ingest.scrape_historical_urls --from-html pagina.html  # sin red
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup

from common.config import get_settings
from common.db import get_connection, utcnow_naive
from common.http import get
from common.logging_utils import get_logger

logger = get_logger(__name__)

_FILE_RE = re.compile(r"\.(csv|zip)(\?.*)?$", re.IGNORECASE)
# Deduce el periodo del DATO (no de la carpeta) buscando YYYY-MM en el nombre.
_PERIOD_RE = re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])")
_YEAR_RE = re.compile(r"(20\d{2})")
# Meses en español (completos y abreviados) para nombres tipo "2024_enero".
_MONTH_ES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9, "sep": 9,
    "sept": 9, "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}
_MONTH_ES_RE = re.compile("|".join(sorted(_MONTH_ES, key=len, reverse=True)), re.IGNORECASE)

MANIFEST_COLUMNS = [
    "url",
    "file_name",
    "year",
    "month",
    "discovered_at_utc",
    "download_status",
    "http_status",
    "size_bytes",
    "checksum_sha256",
    "local_path",
    "last_downloaded_at_utc",
]


def extract_links(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extrae enlaces .csv/.zip de la página y deduce (year, month) del nombre."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not _FILE_RE.search(href):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        file_name = Path(urlparse(url).path).name
        year, month = _infer_period(file_name)
        out.append(
            {
                "url": url,
                "file_name": file_name,
                "year": year,
                "month": month,
            }
        )
    return out


def _infer_period(file_name: str) -> tuple[int | None, int | None]:
    """Deduce (año, mes) del nombre del archivo. Devuelve (None, None) si no puede.

    Prueba primero el patrón numérico ``YYYY-MM`` / ``YYYY_MM`` y, como respaldo,
    nombres de mes en español combinados con un año de 4 dígitos.
    """
    m = _PERIOD_RE.search(file_name)
    if m:
        return int(m.group(1)), int(m.group(2))
    year_m = _YEAR_RE.search(file_name)
    month_m = _MONTH_ES_RE.search(file_name)
    if year_m and month_m:
        return int(year_m.group(1)), _MONTH_ES[month_m.group(0).lower()]
    return None, None


def _load_existing_manifest(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype={"year": "Int64", "month": "Int64"})
    return pd.DataFrame(columns=MANIFEST_COLUMNS)


def merge_manifest(existing: pd.DataFrame, discovered: list[dict[str, Any]]) -> pd.DataFrame:
    """Fusiona lo descubierto con el manifiesto previo, preservando estado."""
    now = utcnow_naive().isoformat()
    existing_by_url = {row["url"]: row for _, row in existing.iterrows()}
    rows: list[dict[str, Any]] = []
    discovered_urls = set()
    for d in discovered:
        discovered_urls.add(d["url"])
        prev = existing_by_url.get(d["url"])
        if prev is not None:
            # Conserva estado de descarga y checksum previos.
            row = {c: prev.get(c) for c in MANIFEST_COLUMNS}
            row.update({"file_name": d["file_name"], "year": d["year"], "month": d["month"]})
        else:
            row = {
                "url": d["url"],
                "file_name": d["file_name"],
                "year": d["year"],
                "month": d["month"],
                "discovered_at_utc": now,
                "download_status": "pending",
                "http_status": pd.NA,
                "size_bytes": pd.NA,
                "checksum_sha256": pd.NA,
                "local_path": pd.NA,
                "last_downloaded_at_utc": pd.NA,
            }
        rows.append(row)
    # Conserva entradas previas que ya no aparecen (histórico retirado de la página).
    for url, prev in existing_by_url.items():
        if url not in discovered_urls:
            rows.append({c: prev.get(c) for c in MANIFEST_COLUMNS})
    df = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    df["year"] = df["year"].astype("Int64")
    df["month"] = df["month"].astype("Int64")
    return df.sort_values(["year", "month", "file_name"], na_position="last").reset_index(drop=True)


def sync_manifest_to_duckdb(df: pd.DataFrame) -> None:
    """Refleja el manifiesto en la tabla historical_file_manifest."""
    con = get_connection()
    con.register("tmp_manifest", df)
    con.execute(
        """
        INSERT INTO historical_file_manifest
            (url, file_name, year, month, discovered_at_utc, download_status,
             http_status, size_bytes, checksum_sha256, local_path, last_downloaded_at_utc)
        SELECT url, file_name, year, month,
               TRY_CAST(discovered_at_utc AS TIMESTAMP), download_status,
               TRY_CAST(http_status AS INTEGER), TRY_CAST(size_bytes AS BIGINT),
               checksum_sha256, local_path,
               TRY_CAST(last_downloaded_at_utc AS TIMESTAMP)
        FROM tmp_manifest t
        WHERE NOT EXISTS (
            SELECT 1 FROM historical_file_manifest m WHERE m.url = t.url
        )
        """
    )
    con.unregister("tmp_manifest")
    con.close()


def scrape(from_html: str | None = None) -> pd.DataFrame:
    """Ejecuta el scraping y actualiza el manifiesto. Devuelve el DataFrame."""
    settings = get_settings()
    base_url = settings.get("sources", "historical_open_data_url")
    if from_html:
        html = Path(from_html).read_text(encoding="utf-8")
    else:
        html = get(base_url).text
    discovered = extract_links(html, base_url)
    logger.info("Descubiertos %d archivos históricos", len(discovered))

    manifest_path = settings.path("manifests") / "ecobici_historico.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_manifest(manifest_path)
    merged = merge_manifest(existing, discovered)
    merged.to_csv(manifest_path, index=False)
    logger.info("Manifiesto escrito en %s (%d filas)", manifest_path, len(merged))
    sync_manifest_to_duckdb(merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Scraper del histórico de ECOBICI.")
    parser.add_argument("--from-html", type=str, default=None, help="HTML local para pruebas.")
    args = parser.parse_args()
    df = scrape(from_html=args.from_html)
    with_period = df.dropna(subset=["year", "month"])
    logger.info(
        "Total: %d archivos, %d con periodo inferido. Rango: %s a %s",
        len(df),
        len(with_period),
        f"{with_period['year'].min()}-{with_period['month'].min():02d}" if len(with_period) else "-",
        f"{with_period['year'].max()}-{with_period['month'].max():02d}" if len(with_period) else "-",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
