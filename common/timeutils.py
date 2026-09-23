"""Utilidades de tiempo y zona horaria (America/Mexico_City por defecto)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Mexico_City"


def get_tz(name: str = DEFAULT_TZ) -> ZoneInfo:
    return ZoneInfo(name)


def now_utc() -> datetime:
    """Instante actual en UTC (aware)."""
    return datetime.now(tz=UTC)


def now_local(tz_name: str = DEFAULT_TZ) -> datetime:
    """Instante actual en la zona local (aware)."""
    return datetime.now(tz=get_tz(tz_name))


def utc_to_local(dt: datetime, tz_name: str = DEFAULT_TZ) -> datetime:
    """Convierte un datetime UTC (aware o naive-asumido-UTC) a local."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(get_tz(tz_name))


def epoch_to_utc(epoch_seconds: int | float) -> datetime:
    """Convierte un timestamp UNIX (segundos) a datetime UTC aware."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)


def iso_utc(dt: datetime | None = None) -> str:
    """ISO-8601 en UTC, útil para claves de ejecución y deduplicado."""
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()
