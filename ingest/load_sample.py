"""Carga los datos de muestra (data/sample/) en DuckDB.

Permite ejecutar el pipeline completo sin red: normaliza los viajes sintéticos y
carga la información y el estado de estaciones. Idempotente: reemplaza las filas
de muestra (run_id = 'sample') en cada corrida.

Uso:
    python -m ingest.load_sample
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common.config import get_settings
from common.db import get_connection, utcnow_naive
from common.logging_utils import get_logger
from transform.normalize_historical import clean_dataframe, read_raw_csv

logger = get_logger(__name__)

SAMPLE_RUN_ID = "sample"


def _ensure_sample_exists() -> Path:
    sample_dir = get_settings().path("sample")
    trips = sample_dir / "sample_trips.csv"
    if not trips.exists():
        logger.info("No hay datos de muestra; generándolos...")
        import runpy

        runpy.run_path(str(sample_dir / "generate_sample.py"), run_name="__main__")
    return sample_dir


def load_sample() -> dict[str, int]:
    sample_dir = _ensure_sample_exists()
    con = get_connection()

    # --- Limpia cualquier carga de muestra previa (idempotencia) ---
    for tbl in ("trips_raw", "trips_clean", "trip_rejections", "station_information", "station_status"):
        con.execute(f"DELETE FROM {tbl} WHERE run_id = ?", [SAMPLE_RUN_ID])

    # --- Viajes: normaliza con las mismas reglas del histórico real ---
    raw = read_raw_csv(sample_dir / "sample_trips.csv")
    clean, rejections, report = clean_dataframe(raw, "sample_trips.csv", SAMPLE_RUN_ID)
    con.register("tmp_clean", clean)
    con.execute("INSERT INTO trips_clean SELECT * FROM tmp_clean")
    con.unregister("tmp_clean")
    con.register("tmp_rej", rejections)
    con.execute("INSERT INTO trip_rejections SELECT * FROM tmp_rej")
    con.unregister("tmp_rej")
    logger.info(
        "Viajes de muestra: %d válidos, %d rechazados (%.2f%%)",
        report["validas"], report["rechazadas"], report["pct_rechazado"],
    )

    # --- Información de estaciones ---
    info = pd.read_csv(sample_dir / "sample_station_information.csv", dtype={"station_id": str})
    info["region_id"] = None
    info["short_name"] = None
    info["captured_at_utc"] = utcnow_naive()
    info["run_id"] = SAMPLE_RUN_ID
    info = info[["station_id", "name", "lat", "lon", "capacity", "region_id",
                 "short_name", "captured_at_utc", "run_id"]]
    con.register("tmp_info", info)
    con.execute("INSERT INTO station_information SELECT * FROM tmp_info")
    con.unregister("tmp_info")

    # --- Estado de estaciones (serie temporal) ---
    status = pd.read_csv(
        sample_dir / "sample_station_status.csv",
        dtype={"station_id": str},
        parse_dates=["captured_at_utc", "captured_at_local", "ingested_at_utc"],
    )
    con.register("tmp_status", status)
    con.execute("INSERT INTO station_status SELECT * FROM tmp_status")
    con.unregister("tmp_status")

    counts = {
        "trips_clean": con.execute(
            "SELECT COUNT(*) FROM trips_clean WHERE run_id='sample'").fetchone()[0],
        "station_information": con.execute(
            "SELECT COUNT(*) FROM station_information WHERE run_id='sample'").fetchone()[0],
        "station_status": con.execute(
            "SELECT COUNT(*) FROM station_status WHERE run_id='sample'").fetchone()[0],
    }
    con.close()
    logger.info("Muestra cargada: %s", counts)
    return counts


def main() -> int:
    load_sample()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
