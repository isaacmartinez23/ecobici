"""Pruebas del colector GBFS: parsing, controles de calidad e idempotencia."""

from __future__ import annotations

from ingest.collect_gbfs import (
    collect_once,
    discover_feeds,
    parse_station_information,
    parse_station_status,
)


def test_discover_feeds_con_idiomas():
    discovery = {
        "data": {
            "es": {"feeds": [{"name": "station_status", "url": "http://x/status"}]},
            "en": {"feeds": [{"name": "station_status", "url": "http://x/en/status"}]},
        }
    }
    feeds = discover_feeds(discovery, language="es")
    assert feeds["station_status"] == "http://x/status"


def test_discover_feeds_gbfs_v3_plano():
    discovery = {"data": {"feeds": [{"name": "station_information", "url": "http://x/info"}]}}
    feeds = discover_feeds(discovery)
    assert feeds["station_information"] == "http://x/info"


def test_parse_station_status_controles(gbfs_status_payload):
    rows, quality = parse_station_status(gbfs_status_payload)
    # station "1" una sola vez (duplicada descartada), "2" y "3" presentes.
    ids = sorted(r["station_id"] for r in rows)
    assert ids == ["1", "2", "3"]
    assert quality["dup_stations"] == 1
    assert quality["negativos"] == 1
    assert quality["sin_station_id"] == 1
    # El negativo se anuló.
    st2 = next(r for r in rows if r["station_id"] == "2")
    assert st2["num_bikes_available"] is None
    # La incompleta tiene None en campos ausentes.
    st3 = next(r for r in rows if r["station_id"] == "3")
    assert st3["num_bikes_available"] is None


def test_parse_station_information_dedup(gbfs_info_payload):
    rows = parse_station_information(gbfs_info_payload)
    assert len(rows) == 3
    assert rows[0]["capacity"] == 15


def test_collector_idempotente(db, gbfs_info_payload, gbfs_status_payload):
    # Primera captura: inserta filas válidas (3 estaciones: 1, 2, 3).
    s1 = collect_once(db, gbfs_info_payload, gbfs_status_payload, run_id="r1")
    assert s1["station_status_insertadas"] == 3
    # Segunda captura con mismos last_reported: no debe insertar nada nuevo.
    s2 = collect_once(db, gbfs_info_payload, gbfs_status_payload, run_id="r2")
    assert s2["station_status_insertadas"] == 0
    total = db.execute("SELECT COUNT(*) FROM station_status").fetchone()[0]
    assert total == 3


def test_collector_inserta_cuando_cambia_last_reported(db, gbfs_info_payload, gbfs_status_payload):
    collect_once(db, gbfs_info_payload, gbfs_status_payload, run_id="r1")
    # Cambiamos last_reported de la estación 1: debe insertarse como captura nueva.
    payload2 = {
        "data": {
            "stations": [
                {
                    "station_id": "1",
                    "num_bikes_available": 2,
                    "num_docks_available": 13,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_700_000_999,
                }
            ]
        }
    }
    s2 = collect_once(db, gbfs_info_payload, payload2, run_id="r2")
    assert s2["station_status_insertadas"] == 1
    n1 = db.execute("SELECT COUNT(*) FROM station_status WHERE station_id='1'").fetchone()[0]
    assert n1 == 2
