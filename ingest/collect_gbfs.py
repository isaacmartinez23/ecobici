"""Colector de disponibilidad GBFS en tiempo real.

El feed GBFS es una fotografía del momento: no contiene historia. Este colector
guarda ``station_status`` (y ``station_information`` cuando cambia) en DuckDB de
forma idempotente, para construir una serie temporal ejecutándolo cada 5 minutos.

Uso:
    python -m ingest.collect_gbfs                # captura real desde la red
    python -m ingest.collect_gbfs --dry-run      # imprime sin escribir en DB
    python -m ingest.collect_gbfs --from-fixture ruta.json  # sin red (pruebas)

Controles de calidad implementados:
    - Respuestas incompletas (claves faltantes -> None).
    - Estaciones duplicadas dentro de un mismo payload (se conserva la primera).
    - Valores negativos de bicis/anclajes (se anulan y se cuentan como anomalías).
    - Fallas transitorias de red (reintentos con backoff en common.http).
    - Deduplicado de capturas por (station_id, last_reported).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from common.config import get_settings
from common.db import finish_run, get_connection, new_run_id, start_run, utcnow_naive
from common.http import get_json
from common.logging_utils import get_logger
from common.timeutils import now_utc, utc_to_local

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Parsing puro (sin red ni DB) — fácil de testear con fixtures.
# --------------------------------------------------------------------------- #
def discover_feeds(discovery: dict[str, Any], language: str = "es") -> dict[str, str]:
    """Extrae {nombre_feed: url} del discovery feed GBFS.

    Soporta el formato con idiomas (``data.<lang>.feeds``, GBFS 1.x/2.x) y el
    formato plano de GBFS 3.x (``data.feeds``).
    """
    data = discovery.get("data", {})
    feeds_list: list[dict[str, Any]] | None = None
    if isinstance(data, dict) and "feeds" in data:  # GBFS 3.x
        feeds_list = data.get("feeds")
    elif isinstance(data, dict):  # GBFS 1.x/2.x con idiomas
        lang_block = data.get(language) or next(iter(data.values()), {})
        feeds_list = lang_block.get("feeds") if isinstance(lang_block, dict) else None
    if not feeds_list:
        raise ValueError("Discovery feed sin lista de feeds reconocible")
    return {f["name"]: f["url"] for f in feeds_list if "name" in f and "url" in f}


def parse_station_information(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza station_information a filas. Tolera claves ausentes."""
    stations = payload.get("data", {}).get("stations", []) or []
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for st in stations:
        sid = st.get("station_id")
        if sid is None or str(sid) in seen:
            continue
        seen.add(str(sid))
        rows.append(
            {
                "station_id": str(sid),
                "name": st.get("name"),
                "lat": _as_float(st.get("lat")),
                "lon": _as_float(st.get("lon")),
                "capacity": _as_int(st.get("capacity")),
                "region_id": _as_str(st.get("region_id")),
                "short_name": _as_str(st.get("short_name")),
            }
        )
    return rows


def parse_station_status(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Normaliza station_status a filas y devuelve (filas, contadores_calidad).

    Contadores: dup_stations, negativos, sin_station_id.
    """
    stations = payload.get("data", {}).get("stations", []) or []
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    quality = {"dup_stations": 0, "negativos": 0, "sin_station_id": 0}
    for st in stations:
        sid = st.get("station_id")
        if sid is None:
            quality["sin_station_id"] += 1
            continue
        sid = str(sid)
        if sid in seen:
            quality["dup_stations"] += 1
            continue
        seen.add(sid)

        bikes = _as_int(st.get("num_bikes_available"))
        docks = _as_int(st.get("num_docks_available"))
        # Control de valores negativos: se anulan y se cuentan.
        if (bikes is not None and bikes < 0) or (docks is not None and docks < 0):
            quality["negativos"] += 1
            bikes = None if (bikes is not None and bikes < 0) else bikes
            docks = None if (docks is not None and docks < 0) else docks

        rows.append(
            {
                "station_id": sid,
                "num_bikes_available": bikes,
                "num_docks_available": docks,
                "is_installed": _as_bool(st.get("is_installed")),
                "is_renting": _as_bool(st.get("is_renting")),
                "is_returning": _as_bool(st.get("is_returning")),
                "last_reported": _as_int(st.get("last_reported")),
            }
        )
    return rows, quality


# --------------------------------------------------------------------------- #
# Coerción defensiva de tipos
# --------------------------------------------------------------------------- #
def _as_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes", "si", "sí"}
    return None


def _as_str(v: Any) -> str | None:
    return str(v) if v is not None else None


# --------------------------------------------------------------------------- #
# Escritura idempotente en DuckDB
# --------------------------------------------------------------------------- #
def _insert_status(con, rows: list[dict[str, Any]], run_id: str) -> int:
    """Inserta capturas nuevas deduplicando por (station_id, last_reported)."""
    if not rows:
        return 0
    captured_utc = now_utc()
    captured_local = utc_to_local(captured_utc)
    df = pd.DataFrame(rows)
    df["capture_id"] = df["station_id"].astype(str) + "|" + df["last_reported"].astype("string")
    df["captured_at_utc"] = captured_utc.replace(tzinfo=None)
    df["captured_at_local"] = captured_local.replace(tzinfo=None)
    df["ingested_at_utc"] = utcnow_naive()
    df["run_id"] = run_id
    df = df[
        [
            "capture_id",
            "station_id",
            "num_bikes_available",
            "num_docks_available",
            "is_installed",
            "is_renting",
            "is_returning",
            "last_reported",
            "captured_at_utc",
            "captured_at_local",
            "ingested_at_utc",
            "run_id",
        ]
    ]
    con.register("tmp_status", df)
    before = con.execute("SELECT COUNT(*) FROM station_status").fetchone()[0]
    con.execute(
        """
        INSERT INTO station_status
        SELECT t.* FROM tmp_status t
        WHERE t.last_reported IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM station_status s
               WHERE s.station_id = t.station_id
                 AND s.last_reported = t.last_reported
           )
        """
    )
    after = con.execute("SELECT COUNT(*) FROM station_status").fetchone()[0]
    con.unregister("tmp_status")
    return int(after - before)


def _insert_information(con, rows: list[dict[str, Any]], run_id: str) -> int:
    """Inserta información de estaciones solo si cambió respecto a lo último."""
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df["captured_at_utc"] = utcnow_naive()
    df["run_id"] = run_id
    df = df[
        [
            "station_id",
            "name",
            "lat",
            "lon",
            "capacity",
            "region_id",
            "short_name",
            "captured_at_utc",
            "run_id",
        ]
    ]
    con.register("tmp_info", df)
    before = con.execute("SELECT COUNT(*) FROM station_information").fetchone()[0]
    # Inserta si no existe una fila reciente idéntica (mismo id/nombre/lat/lon/capacidad).
    con.execute(
        """
        INSERT INTO station_information
        SELECT t.* FROM tmp_info t
        WHERE NOT EXISTS (
            SELECT 1 FROM station_information s
            WHERE s.station_id = t.station_id
              AND s.name IS NOT DISTINCT FROM t.name
              AND s.lat IS NOT DISTINCT FROM t.lat
              AND s.lon IS NOT DISTINCT FROM t.lon
              AND s.capacity IS NOT DISTINCT FROM t.capacity
        )
        """
    )
    after = con.execute("SELECT COUNT(*) FROM station_information").fetchone()[0]
    con.unregister("tmp_info")
    return int(after - before)


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def load_payloads_from_network() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Descarga discovery + station_information + station_status desde la red."""
    settings = get_settings()
    discovery_url = settings.get("sources", "gbfs_discovery_url")
    language = settings.get("sources", "gbfs_language", default="es")
    discovery = get_json(discovery_url)
    feeds = discover_feeds(discovery, language)
    if "station_information" not in feeds or "station_status" not in feeds:
        raise ValueError(f"Feeds requeridos ausentes. Disponibles: {list(feeds)}")
    info = get_json(feeds["station_information"])
    status = get_json(feeds["station_status"])
    return discovery, info, status


def collect_once(
    con,
    info_payload: dict[str, Any],
    status_payload: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Procesa un par de payloads y escribe en DB. Devuelve un resumen."""
    info_rows = parse_station_information(info_payload)
    status_rows, quality = parse_station_status(status_payload)
    n_info = _insert_information(con, info_rows, run_id)
    n_status = _insert_status(con, status_rows, run_id)
    summary = {
        "run_id": run_id,
        "station_information_leidas": len(info_rows),
        "station_information_insertadas": n_info,
        "station_status_leidas": len(status_rows),
        "station_status_insertadas": n_status,
        "calidad": quality,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Colector GBFS de ECOBICI.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en DB.")
    parser.add_argument(
        "--from-fixture",
        type=str,
        default=None,
        help="Ruta a un JSON con {'station_information':..., 'station_status':...} para pruebas sin red.",
    )
    args = parser.parse_args()

    if args.from_fixture:
        payload = json.loads(Path(args.from_fixture).read_text(encoding="utf-8"))
        info_payload = payload["station_information"]
        status_payload = payload["station_status"]
    else:
        _, info_payload, status_payload = load_payloads_from_network()

    if args.dry_run:
        info_rows = parse_station_information(info_payload)
        status_rows, quality = parse_station_status(status_payload)
        logger.info(
            "DRY-RUN: %d estaciones info, %d status, calidad=%s",
            len(info_rows),
            len(status_rows),
            quality,
        )
        return 0

    con = get_connection()
    run_id = new_run_id("gbfs")
    start_run(con, run_id, "gbfs", source="gbfs.mex.lyftbikes.com")
    try:
        summary = collect_once(con, info_payload, status_payload, run_id)
        finish_run(
            con,
            run_id,
            "ok",
            rows_ingested=summary["station_status_insertadas"],
            notes=json.dumps(summary["calidad"]),
        )
        logger.info("Captura GBFS OK: %s", summary)
    except Exception as exc:  # noqa: BLE001 — registramos y re-lanzamos
        finish_run(con, run_id, "error", notes=str(exc))
        logger.exception("Fallo en la captura GBFS")
        con.close()
        raise
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
