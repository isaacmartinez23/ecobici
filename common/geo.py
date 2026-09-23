"""Operaciones geográficas mínimas.

Se usa haversine puro (sin dependencias) para que el pipeline funcione aunque
GeoPandas no esté instalado. Si GeoPandas está disponible, otros módulos pueden
usarlo para operaciones más ricas, pero no es obligatorio.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos (lat/lon en grados)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def nearest(
    lat: float,
    lon: float,
    candidates: Iterable[tuple[object, float, float]],
) -> tuple[object, float] | None:
    """Devuelve (id_candidato, distancia_m) del candidato más cercano.

    ``candidates`` es un iterable de tuplas ``(id, lat, lon)``. Devuelve ``None``
    si no hay candidatos válidos.
    """
    best_id: object | None = None
    best_dist = math.inf
    for cid, clat, clon in candidates:
        if clat is None or clon is None:
            continue
        d = haversine_m(lat, lon, float(clat), float(clon))
        if d < best_dist:
            best_dist = d
            best_id = cid
    if best_id is None:
        return None
    return best_id, best_dist
