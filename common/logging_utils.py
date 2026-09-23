"""Logging estructurado y consistente para todos los scripts del proyecto."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def setup_logging(level: str = "INFO") -> None:
    """Configura el logging raíz una sola vez (idempotente)."""
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(level.upper())
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Devuelve un logger listo para usar, configurando el root si hace falta."""
    setup_logging(level)
    return logging.getLogger(name)
