"""Prepara DuckDB: inicializa el esquema, sincroniza el manifiesto y, opcional-
mente, deja en staging los CSV crudos descargados en ``trips_raw``.

El flujo normal usa ``transform.normalize_historical`` (que carga crudo + limpio
en una sola pasada). Este script existe para (a) crear/verificar el esquema de
forma idempotente y (b) permitir cargar SOLO la capa cruda con ``--stage`` cuando
se quiere inspeccionar los datos antes de limpiarlos.

Uso:
    python -m ingest.load_raw_to_duckdb            # crea esquema + estado
    python -m ingest.load_raw_to_duckdb --stage    # además, staging de crudos
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common.config import get_settings
from common.db import get_connection, new_run_id, table_count, utcnow_naive
from common.logging_utils import get_logger
from transform.normalize_historical import CANONICAL_COLUMNS, _row_hashes, read_raw_csv
from transform.parsing import normalize_columns

logger = get_logger(__name__)

_TABLES = [
    "ingestion_runs", "historical_file_manifest", "trips_raw", "trips_clean",
    "trip_rejections", "station_information", "station_status", "station_bridge",
    "demand_hourly", "availability_hourly", "model_features", "model_predictions",
    "rebalance_recommendations",
]


def _downloaded_files() -> list[str]:
    manifest = get_settings().path("manifests") / "ecobici_historico.csv"
    if not manifest.exists():
        return []
    df = pd.read_csv(manifest)
    ok = df[df["download_status"] == "downloaded"].dropna(subset=["local_path"])
    return [p for p in ok["local_path"].tolist() if Path(p).exists()]


def stage_raw(con, files: list[str]) -> int:
    """Carga los CSV crudos en trips_raw (sin limpieza)."""
    run_id = new_run_id("stage_raw")
    total = 0
    for f in files:
        raw = normalize_columns(read_raw_csv(f))
        for col in CANONICAL_COLUMNS:
            if col not in raw.columns:
                raw[col] = pd.NA
        out = raw[CANONICAL_COLUMNS].copy()
        out["row_hash"] = _row_hashes(normalize_columns(read_raw_csv(f)), Path(f).name).values
        out["source_file"] = Path(f).name
        out["run_id"] = run_id
        out["ingested_at_utc"] = utcnow_naive()
        con.register("tmp_stage", out)
        con.execute(
            """
            INSERT INTO trips_raw
                (row_hash, source_file, run_id, ingested_at_utc, genero_usuario, edad_usuario,
                 bici, ciclo_estacion_retiro, fecha_retiro, hora_retiro,
                 ciclo_estacion_arribo, fecha_arribo, hora_arribo)
            SELECT row_hash, source_file, run_id, ingested_at_utc, genero_usuario, edad_usuario,
                   bici, ciclo_estacion_retiro, fecha_retiro, hora_retiro,
                   ciclo_estacion_arribo, fecha_arribo, hora_arribo
            FROM tmp_stage
            """
        )
        con.unregister("tmp_stage")
        total += len(out)
        logger.info("Staging %s: %d filas", Path(f).name, len(out))
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializa DuckDB y stagea crudos.")
    parser.add_argument("--stage", action="store_true", help="Carga CSV crudos en trips_raw.")
    args = parser.parse_args()

    con = get_connection()  # crea el esquema
    if args.stage:
        files = _downloaded_files()
        if files:
            stage_raw(con, files)
        else:
            logger.warning("No hay archivos descargados para staging.")

    logger.info("Estado de tablas:")
    for t in _TABLES:
        logger.info("  %-28s %d filas", t, table_count(con, t))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
