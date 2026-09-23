"""Carga y acceso a la configuración central del proyecto.

La configuración vive en ``config/settings.yaml`` y puede sobreescribirse con
variables de entorno (útil para CI y despliegues). El objetivo es tener un único
punto de verdad para rutas, umbrales y parámetros.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Raíz del repositorio: config.py está en common/, la raíz es su padre.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"

# Mapeo variable de entorno -> ruta dentro del YAML (lista de claves).
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "ECOBICI_DUCKDB_PATH": ("paths", "duckdb"),
    "ECOBICI_TIMEZONE": ("project", "timezone"),
    "ECOBICI_LOG_LEVEL": ("logging", "level"),
}


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Aplica sobreescrituras desde variables de entorno de forma explícita."""
    for env_key, path in _ENV_OVERRIDES.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        node = data
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return data


@dataclass(frozen=True)
class Settings:
    """Vista tipada y conveniente de la configuración."""

    raw: dict[str, Any]

    # --- Acceso genérico ---
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    # --- Rutas (resueltas contra la raíz del repo) ---
    def path(self, name: str) -> Path:
        rel = self.get("paths", name)
        if rel is None:
            raise KeyError(f"Ruta desconocida en settings.paths: {name!r}")
        p = Path(rel)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def duckdb_path(self) -> Path:
        return self.path("duckdb")

    @property
    def timezone(self) -> str:
        return self.get("project", "timezone", default="America/Mexico_City")

    @property
    def random_seed(self) -> int:
        return int(self.get("project", "random_seed", default=42))

    @property
    def log_level(self) -> str:
        return str(self.get("logging", "level", default="INFO"))


@lru_cache(maxsize=4)
def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    """Carga la configuración (cacheada). ``path`` permite pruebas aisladas."""
    settings_path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
    with open(settings_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data = _apply_env_overrides(data)
    return Settings(raw=data)


def get_settings() -> Settings:
    """Atajo para el caso común."""
    return load_settings()
