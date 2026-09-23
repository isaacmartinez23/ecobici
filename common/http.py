"""Cliente HTTP con reintentos, timeout y user-agent consistente."""

from __future__ import annotations

import time
from typing import Any

import requests

from common.config import get_settings
from common.logging_utils import get_logger

logger = get_logger(__name__)


class HttpError(RuntimeError):
    """Error HTTP tras agotar los reintentos."""


def _cfg() -> dict[str, Any]:
    s = get_settings()
    return {
        "timeout": float(s.get("ingestion", "http_timeout_seconds", default=30)),
        "retries": int(s.get("ingestion", "http_max_retries", default=4)),
        "backoff": float(s.get("ingestion", "http_backoff_seconds", default=2.0)),
        "user_agent": str(s.get("ingestion", "user_agent", default="ecobici-demanda/0.1")),
    }


def get(url: str, *, stream: bool = False, **kwargs: Any) -> requests.Response:
    """GET con reintentos exponenciales. Lanza HttpError si todos fallan."""
    cfg = _cfg()
    headers = {"User-Agent": cfg["user_agent"], **kwargs.pop("headers", {})}
    last_exc: Exception | None = None
    for attempt in range(1, cfg["retries"] + 1):
        try:
            resp = requests.get(
                url, timeout=cfg["timeout"], headers=headers, stream=stream, **kwargs
            )
            # Reintentar solo en errores transitorios del servidor.
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except (requests.RequestException, requests.HTTPError) as exc:
            last_exc = exc
            wait = cfg["backoff"] * (2 ** (attempt - 1))
            logger.warning(
                "GET %s falló (intento %d/%d): %s. Reintentando en %.1fs",
                url,
                attempt,
                cfg["retries"],
                exc,
                wait,
            )
            if attempt < cfg["retries"]:
                time.sleep(wait)
    raise HttpError(f"GET {url} falló tras {cfg['retries']} intentos: {last_exc}")


def get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    """GET que devuelve JSON parseado."""
    return get(url, **kwargs).json()
