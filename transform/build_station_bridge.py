"""Construye la tabla puente entre IDs históricos y GBFS.

Los identificadores del histórico y de GBFS pueden no coincidir. Se emparejan
por, en orden de prioridad:

    1. Alias manual (config/station_aliases.csv).
    2. Coincidencia exacta de ID.
    3. Nombre normalizado idéntico.
    4. Nombre aproximado (similitud >= umbral).
    5. Distancia geográfica (<= umbral) cuando el histórico tiene coordenadas.

El histórico de viajes de ECOBICI solo trae IDs de estación (sin nombre ni
coordenadas), por lo que en la práctica domina la coincidencia exacta de ID; los
demás métodos se aplican cuando se dispone de un catálogo histórico enriquecido
(``data/interim/historical_stations.csv``) o de alias manuales.

Uso:
    python -m transform.build_station_bridge
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from common.config import REPO_ROOT, get_settings
from common.db import get_connection
from common.geo import haversine_m
from common.logging_utils import get_logger

logger = get_logger(__name__)


def normalize_name(name: str | None) -> str:
    """Normaliza un nombre de estación: sin acentos, minúsculas, colapsado."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_stations(
    hist: pd.DataFrame,
    gbfs: pd.DataFrame,
    aliases: dict[str, str] | None = None,
    min_name_similarity: float = 0.82,
    max_match_distance_m: float = 120.0,
) -> pd.DataFrame:
    """Empareja estaciones históricas con GBFS. Devuelve el DataFrame puente.

    ``hist`` requiere columna ``historico_id`` y opcionalmente ``nombre``,
    ``lat``, ``lon``. ``gbfs`` requiere ``gbfs_id``, ``nombre``, ``lat``, ``lon``.
    """
    aliases = aliases or {}
    gbfs = gbfs.copy()
    gbfs["nombre_norm"] = gbfs["nombre"].map(normalize_name)
    gbfs_ids = set(gbfs["gbfs_id"].astype(str))
    gbfs_by_id = gbfs.set_index(gbfs["gbfs_id"].astype(str))
    name_to_id = {
        n: i for n, i in zip(gbfs["nombre_norm"], gbfs["gbfs_id"].astype(str), strict=False) if n
    }

    rows: list[dict[str, Any]] = []
    for _, h in hist.iterrows():
        hid = str(h["historico_id"])
        hname = h.get("nombre")
        hlat, hlon = h.get("lat"), h.get("lon")
        match = _match_one(
            hid, hname, hlat, hlon, aliases, gbfs_ids, gbfs_by_id, gbfs,
            name_to_id, min_name_similarity, max_match_distance_m,
        )
        match["historico_id"] = hid
        match["nombre_historico"] = hname
        rows.append(match)
    return pd.DataFrame(rows)


def _match_one(
    hid, hname, hlat, hlon, aliases, gbfs_ids, gbfs_by_id, gbfs, name_to_id,
    min_sim, max_dist,
) -> dict[str, Any]:
    def result(gid, method, conf, dist=None):
        g = gbfs_by_id.loc[gid] if gid is not None and gid in gbfs_by_id.index else None
        return {
            "gbfs_id": gid,
            "nombre_gbfs": None if g is None else g["nombre"],
            "lat": None if g is None else g["lat"],
            "lon": None if g is None else g["lon"],
            "match_method": method,
            "confidence": conf,
            "distance_m": dist,
            "manual_review": method in ("fuzzy_name", "geo") or method == "unmatched",
        }

    # 1. Alias manual
    if hid in aliases and aliases[hid] in gbfs_ids:
        return result(aliases[hid], "manual_alias", 1.0)
    # 2. Exacto por ID
    if hid in gbfs_ids:
        return result(hid, "exact_id", 1.0, 0.0)
    # 3. Nombre normalizado idéntico
    hn = normalize_name(hname)
    if hn and hn in name_to_id:
        return result(name_to_id[hn], "norm_name", 0.95)
    # 4. Nombre aproximado
    if hn:
        best_id, best_sim = None, 0.0
        for n, gid in name_to_id.items():
            sim = _similarity(hn, n)
            if sim > best_sim:
                best_id, best_sim = gid, sim
        if best_id is not None and best_sim >= min_sim:
            return result(best_id, "fuzzy_name", round(best_sim, 3))
    # 5. Geografía
    if hlat is not None and hlon is not None and not pd.isna(hlat) and not pd.isna(hlon):
        best_id, best_dist = None, float("inf")
        for _, g in gbfs.iterrows():
            if pd.isna(g["lat"]) or pd.isna(g["lon"]):
                continue
            d = haversine_m(float(hlat), float(hlon), float(g["lat"]), float(g["lon"]))
            if d < best_dist:
                best_id, best_dist = str(g["gbfs_id"]), d
        if best_id is not None and best_dist <= max_dist:
            conf = round(max(0.0, 1.0 - best_dist / max_dist), 3)
            return result(best_id, "geo", conf, round(best_dist, 1))
    # 6. Sin emparejar
    return result(None, "unmatched", 0.0)


def _load_aliases() -> dict[str, str]:
    path = REPO_ROOT / "config" / "station_aliases.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, comment="#", dtype=str).dropna(subset=["historico_id", "gbfs_id"])
    return dict(zip(df["historico_id"].astype(str), df["gbfs_id"].astype(str), strict=False))


def _historical_stations(con) -> pd.DataFrame:
    """IDs históricos desde trips_clean, enriquecidos con catálogo si existe."""
    ids = con.execute(
        """
        SELECT DISTINCT station_id FROM (
            SELECT origin_station_id AS station_id FROM trips_clean
            UNION
            SELECT dest_station_id AS station_id FROM trips_clean
        ) WHERE station_id IS NOT NULL
        """
    ).df()
    ids = ids.rename(columns={"station_id": "historico_id"})
    ids["nombre"] = None
    ids["lat"] = None
    ids["lon"] = None

    catalog = get_settings().path("interim") / "historical_stations.csv"
    if catalog.exists():
        cat = pd.read_csv(catalog, dtype={"historico_id": str})
        ids = ids.drop(columns=["nombre", "lat", "lon"]).merge(
            cat, on="historico_id", how="left"
        )
        logger.info("Catálogo histórico encontrado: %s", catalog)
    return ids


def _gbfs_stations(con) -> pd.DataFrame:
    """Última información conocida por estación GBFS."""
    df = con.execute(
        """
        SELECT station_id AS gbfs_id, name AS nombre, lat, lon
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY station_id ORDER BY captured_at_utc DESC
            ) AS rn
            FROM station_information
        ) WHERE rn = 1
        """
    ).df()
    return df


def build() -> dict[str, Any]:
    settings = get_settings()
    con = get_connection()
    hist = _historical_stations(con)
    gbfs = _gbfs_stations(con)
    if gbfs.empty:
        logger.warning("No hay station_information; el puente quedará sin emparejar.")
    bridge = match_stations(
        hist,
        gbfs,
        aliases=_load_aliases(),
        min_name_similarity=float(settings.get("station_bridge", "min_name_similarity", default=0.82)),
        max_match_distance_m=float(settings.get("station_bridge", "max_match_distance_m", default=120.0)),
    )

    con.execute("DELETE FROM station_bridge")
    cols = ["historico_id", "gbfs_id", "nombre_historico", "nombre_gbfs", "lat", "lon",
            "match_method", "confidence", "distance_m", "manual_review"]
    con.register("tmp_bridge", bridge[cols])
    con.execute(f"INSERT INTO station_bridge SELECT {', '.join(cols)} FROM tmp_bridge")
    con.unregister("tmp_bridge")

    # --- Cobertura ---
    n_hist = len(hist)
    n_matched = int((bridge["gbfs_id"].notna()).sum())
    trip_cov = con.execute(
        """
        SELECT
            AVG(CASE WHEN b1.gbfs_id IS NOT NULL AND b2.gbfs_id IS NOT NULL
                     THEN 1.0 ELSE 0.0 END) AS cobertura
        FROM trips_clean t
        LEFT JOIN station_bridge b1 ON t.origin_station_id = b1.historico_id
        LEFT JOIN station_bridge b2 ON t.dest_station_id = b2.historico_id
        """
    ).fetchone()[0]
    con.close()

    coverage = {
        "estaciones_historicas": n_hist,
        "estaciones_emparejadas": n_matched,
        "pct_estaciones": round(100 * n_matched / n_hist, 2) if n_hist else 0.0,
        "pct_viajes_cubiertos": round(100 * (trip_cov or 0.0), 2),
        "por_metodo": bridge["match_method"].value_counts().to_dict(),
    }
    logger.info("Puente de estaciones: %s", coverage)
    return coverage


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
