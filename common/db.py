"""Gestión de la conexión DuckDB y creación idempotente del esquema."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import duckdb

from common.config import REPO_ROOT, get_settings
from common.logging_utils import get_logger
from common.timeutils import now_utc

logger = get_logger(__name__)

SCHEMA_PATH = REPO_ROOT / "common" / "schema.sql"


def connect(db_path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre una conexión DuckDB. Crea el directorio padre si no existe."""
    settings = get_settings()
    path = Path(db_path) if db_path is not None else settings.duckdb_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Crea todas las tablas si no existen (idempotente)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    con.execute(sql)
    logger.debug("Esquema inicializado desde %s", SCHEMA_PATH)


def get_connection(
    db_path: str | Path | None = None, ensure_schema: bool = True
) -> duckdb.DuckDBPyConnection:
    """Conexión lista para usar, con el esquema garantizado."""
    con = connect(db_path)
    if ensure_schema:
        init_schema(con)
    return con


def new_run_id(prefix: str) -> str:
    """Genera un identificador de ejecución único y ordenable por tiempo."""
    stamp = now_utc().strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def start_run(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    run_type: str,
    source: str | None = None,
) -> None:
    """Registra el inicio de una ejecución en ingestion_runs."""
    con.execute(
        """
        INSERT INTO ingestion_runs (run_id, run_type, source, started_at_utc, status)
        VALUES (?, ?, ?, ?, 'running')
        """,
        [run_id, run_type, source, now_utc().replace(tzinfo=None)],
    )


def finish_run(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    status: str,
    rows_ingested: int = 0,
    notes: str | None = None,
) -> None:
    """Marca el fin de una ejecución."""
    con.execute(
        """
        UPDATE ingestion_runs
        SET finished_at_utc = ?, status = ?, rows_ingested = ?, notes = ?
        WHERE run_id = ?
        """,
        [now_utc().replace(tzinfo=None), status, rows_ingested, notes, run_id],
    )


def table_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Número de filas de una tabla (0 si no existe)."""
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except duckdb.CatalogException:
        return 0


def utcnow_naive() -> datetime:
    """UTC actual sin tzinfo, para columnas TIMESTAMP de DuckDB."""
    return now_utc().replace(tzinfo=None)
