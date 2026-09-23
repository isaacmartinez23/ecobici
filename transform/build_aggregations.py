"""Ejecuta las agregaciones SQL por hora (demanda y disponibilidad).

Uso:
    python -m transform.build_aggregations
"""

from __future__ import annotations

from common.config import REPO_ROOT
from common.db import get_connection, table_count
from common.logging_utils import get_logger

logger = get_logger(__name__)

SQL_FILES = [
    "build_trip_facts.sql",
    "demand_by_hour.sql",
    "availability_by_hour.sql",
]


def run() -> dict[str, int]:
    con = get_connection()
    for name in SQL_FILES:
        sql = (REPO_ROOT / "transform" / name).read_text(encoding="utf-8")
        con.execute(sql)
        logger.info("Ejecutado %s", name)
    counts = {
        "demand_hourly": table_count(con, "demand_hourly"),
        "availability_hourly": table_count(con, "availability_hourly"),
    }
    con.close()
    logger.info("Agregaciones listas: %s", counts)
    return counts


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
