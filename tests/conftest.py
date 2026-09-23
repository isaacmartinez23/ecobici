"""Fixtures compartidas para las pruebas."""

from __future__ import annotations

import pytest

from common.db import get_connection


@pytest.fixture
def db(tmp_path):
    """Conexión DuckDB temporal con el esquema inicializado."""
    path = tmp_path / "test.duckdb"
    con = get_connection(db_path=path)
    yield con
    con.close()


@pytest.fixture
def gbfs_status_payload():
    """Payload sintético de station_status con casos límite."""
    return {
        "data": {
            "stations": [
                {
                    "station_id": "1",
                    "num_bikes_available": 5,
                    "num_docks_available": 10,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_700_000_000,
                },
                {  # duplicada: debe descartarse
                    "station_id": "1",
                    "num_bikes_available": 7,
                    "num_docks_available": 8,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_700_000_000,
                },
                {  # negativo: se anula y se cuenta
                    "station_id": "2",
                    "num_bikes_available": -3,
                    "num_docks_available": 12,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_700_000_050,
                },
                {  # incompleta: faltan claves
                    "station_id": "3",
                    "last_reported": 1_700_000_060,
                },
                {  # sin station_id: se descarta
                    "num_bikes_available": 4,
                    "last_reported": 1_700_000_070,
                },
            ]
        }
    }


@pytest.fixture
def gbfs_info_payload():
    """Payload sintético de station_information."""
    return {
        "data": {
            "stations": [
                {"station_id": "1", "name": "Estación 1", "lat": 19.42, "lon": -99.16, "capacity": 15},
                {"station_id": "2", "name": "Estación 2", "lat": 19.43, "lon": -99.17, "capacity": 20},
                {"station_id": "3", "name": "Estación 3", "lat": 19.44, "lon": -99.18, "capacity": 12},
            ]
        }
    }
