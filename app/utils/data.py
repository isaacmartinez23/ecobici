"""Capa de acceso a datos para la app Streamlit (lectura de DuckDB).

Todas las funciones abren la base en modo solo-lectura y devuelven DataFrames,
por lo que se cachean bien con ``st.cache_data``. Degradan con elegancia cuando
las tablas están vacías (devuelven DataFrames vacíos con las columnas esperadas).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from common.config import REPO_ROOT, get_settings

# Base de muestra prelista y versionada, usada como respaldo del demo (p. ej. en
# Streamlit Community Cloud, donde no existe la base construida localmente).
SAMPLE_DB = REPO_ROOT / "data" / "sample" / "ecobici_sample.duckdb"


def _has_predictions(path: Path) -> bool:
    """True si la base existe y tiene predicciones (build completo y legible)."""
    if not path.exists():
        return False
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            n = con.execute("SELECT COUNT(*) FROM model_predictions").fetchone()[0]
            return int(n) > 0
    except duckdb.Error:
        return False


def db_path() -> Path:
    """Base a usar: la configurada si está COMPLETA; si no, la muestra prelista.

    Así la app siempre muestra algo completo: en un despliegue limpio —o con una
    base configurada incompleta, p. ej. un build interrumpido en la nube— cae a la
    base de muestra versionada, sin sobrescribir una base real existente.
    """
    configured = get_settings().duckdb_path
    if _has_predictions(configured):
        return configured
    if SAMPLE_DB.exists():
        return SAMPLE_DB
    return configured


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path()), read_only=True)


def _q(sql: str, params: list | None = None) -> pd.DataFrame:
    try:
        with _con() as con:
            return con.execute(sql, params or []).df()
    except (duckdb.CatalogException, duckdb.IOException, duckdb.Error):
        return pd.DataFrame()


def has_data() -> bool:
    df = _q("SELECT COUNT(*) AS n FROM trips_clean")
    return (not df.empty) and int(df["n"].iloc[0]) > 0


# --------------------------------------------------------------------------- #
# Resumen ejecutivo
# --------------------------------------------------------------------------- #
def summary() -> dict:
    trips = _q(
        "SELECT COUNT(*) n, MIN(retiro_ts) tmin, MAX(retiro_ts) tmax, "
        "COUNT(DISTINCT origin_station_id) est FROM trips_clean"
    )
    rej = _q("SELECT COUNT(*) n FROM trip_rejections")
    n_trips = int(trips["n"].iloc[0]) if not trips.empty else 0
    n_rej = int(rej["n"].iloc[0]) if not rej.empty else 0
    total = n_trips + n_rej
    ev = _q("SELECT * FROM model_predictions WHERE split='test'")
    mae_base = mae_model = None
    if not ev.empty:
        mae_base = float((ev["y_true"] - ev["y_pred_baseline"]).abs().mean())
        mae_model = float((ev["y_true"] - ev["y_pred_model"]).abs().mean())
    return {
        "n_trips": n_trips,
        "n_rejected": n_rej,
        "pct_rejected": round(100 * n_rej / total, 2) if total else 0.0,
        "n_stations": int(trips["est"].iloc[0]) if not trips.empty else 0,
        "period_min": None if trips.empty else trips["tmin"].iloc[0],
        "period_max": None if trips.empty else trips["tmax"].iloc[0],
        "mae_base": mae_base,
        "mae_model": mae_model,
    }


# --------------------------------------------------------------------------- #
# Estaciones con métricas de riesgo (para el mapa y el ranking)
# --------------------------------------------------------------------------- #
def stations_risk() -> pd.DataFrame:
    """Estaciones con demanda media, riesgo de vaciado y saturación."""
    return _q(
        """
        WITH info AS (
            SELECT station_id, name, lat, lon, capacity FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
                FROM station_information
            ) WHERE rn = 1
        ),
        dem AS (
            SELECT b.gbfs_id AS station_id, AVG(d.salidas) AS demanda_media
            FROM demand_hourly d
            JOIN station_bridge b ON d.station_id = b.historico_id
            GROUP BY 1
        ),
        avail AS (
            SELECT station_id,
                   AVG(CASE WHEN empty_flag THEN 1.0 ELSE 0.0 END) AS riesgo_vaciado,
                   AVG(CASE WHEN full_flag THEN 1.0 ELSE 0.0 END) AS riesgo_saturacion,
                   SUM(minutes_zero_bikes) AS min_sin_bicis
            FROM availability_hourly GROUP BY 1
        ),
        last_status AS (
            SELECT station_id, num_bikes_available AS bicis_actuales FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
                FROM station_status
            ) WHERE rn = 1
        )
        SELECT i.station_id, i.name, i.lat, i.lon, i.capacity,
               COALESCE(d.demanda_media, 0) AS demanda_media,
               COALESCE(a.riesgo_vaciado, 0) AS riesgo_vaciado,
               COALESCE(a.riesgo_saturacion, 0) AS riesgo_saturacion,
               COALESCE(a.min_sin_bicis, 0) AS min_sin_bicis,
               ls.bicis_actuales
        FROM info i
        LEFT JOIN dem d USING (station_id)
        LEFT JOIN avail a USING (station_id)
        LEFT JOIN last_status ls USING (station_id)
        ORDER BY riesgo_vaciado DESC, demanda_media DESC
        """
    )


def stations_risk_filtered(dows: list[int], hour: int) -> pd.DataFrame:
    """Riesgo por estación para un día de semana y hora concretos.

    Riesgo de vaciado se estima con la tasa de horas con estación vacía en esa
    franja; demanda con las salidas medias en la franja. Si no hay filas para el
    filtro, devuelve el resumen global (``stations_risk``).
    """
    if not dows:
        return stations_risk()
    placeholders = ",".join("?" for _ in dows)
    df = _q(
        f"""
        WITH info AS (
            SELECT station_id, name, lat, lon, capacity FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
                FROM station_information
            ) WHERE rn = 1
        ),
        dem AS (
            SELECT b.gbfs_id AS station_id, AVG(d.salidas) AS demanda_media
            FROM demand_hourly d
            JOIN station_bridge b ON d.station_id = b.historico_id
            WHERE d.dow IN ({placeholders}) AND d.hour = ?
            GROUP BY 1
        ),
        avail AS (
            SELECT station_id,
                   AVG(CASE WHEN empty_flag THEN 1.0 ELSE 0.0 END) AS riesgo_vaciado,
                   AVG(CASE WHEN full_flag THEN 1.0 ELSE 0.0 END) AS riesgo_saturacion,
                   SUM(minutes_zero_bikes) AS min_sin_bicis
            FROM availability_hourly
            WHERE ((CAST(EXTRACT(dow FROM date) AS INTEGER) + 6) % 7) IN ({placeholders})
              AND hour = ?
            GROUP BY 1
        )
        SELECT i.station_id, i.name, i.lat, i.lon, i.capacity,
               COALESCE(d.demanda_media, 0) AS demanda_media,
               COALESCE(a.riesgo_vaciado, 0) AS riesgo_vaciado,
               COALESCE(a.riesgo_saturacion, 0) AS riesgo_saturacion,
               COALESCE(a.min_sin_bicis, 0) AS min_sin_bicis
        FROM info i
        LEFT JOIN dem d USING (station_id)
        LEFT JOIN avail a USING (station_id)
        ORDER BY riesgo_vaciado DESC, demanda_media DESC
        """,
        [*dows, hour, *dows, hour],
    )
    if df.empty or df["demanda_media"].fillna(0).sum() == 0:
        return stations_risk()
    return df


# --------------------------------------------------------------------------- #
# Demanda y predicción por estación
# --------------------------------------------------------------------------- #
def station_list() -> list[str]:
    df = _q("SELECT DISTINCT station_id FROM demand_hourly ORDER BY 1")
    return df["station_id"].tolist() if not df.empty else []


def demand_profile(station_id: str) -> pd.DataFrame:
    """Perfil promedio salidas/llegadas/flujo por hora del día."""
    return _q(
        """
        SELECT hour,
               AVG(salidas) AS salidas,
               AVG(llegadas) AS llegadas,
               AVG(flujo_neto) AS flujo_neto
        FROM demand_hourly WHERE station_id = ?
        GROUP BY hour ORDER BY hour
        """,
        [station_id],
    )


def demand_timeseries(station_id: str) -> pd.DataFrame:
    """Serie temporal observada y predicha (mapea gbfs->historico si aplica)."""
    return _q(
        """
        SELECT ts, y_true AS observado, y_pred_baseline AS linea_base,
               y_pred_model AS modelo, split
        FROM model_predictions
        WHERE station_id = ? AND target = 'salidas'
        ORDER BY ts
        """,
        [station_id],
    )


def availability_profile(station_id: str) -> pd.DataFrame:
    return _q(
        """
        SELECT hour, AVG(bikes_start) AS bicis_promedio,
               AVG(minutes_zero_bikes) AS min_sin_bicis
        FROM availability_hourly
        WHERE station_id IN (SELECT gbfs_id FROM station_bridge WHERE historico_id = ?)
        GROUP BY hour ORDER BY hour
        """,
        [station_id],
    )


# --------------------------------------------------------------------------- #
# Rebalanceo
# --------------------------------------------------------------------------- #
def rebalance_moves() -> pd.DataFrame:
    return _q("SELECT * FROM rebalance_recommendations ORDER BY bikes_to_move DESC")


def rebalance_map_data() -> pd.DataFrame:
    """Movimientos con coordenadas de donante y receptora para el mapa."""
    return _q(
        """
        WITH info AS (
            SELECT station_id, lat, lon FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
                FROM station_information
            ) WHERE rn = 1
        )
        SELECT r.donor_station_id, r.receiver_station_id, r.bikes_to_move,
               di.lat AS donor_lat, di.lon AS donor_lon,
               ri.lat AS recv_lat, ri.lon AS recv_lon
        FROM rebalance_recommendations r
        LEFT JOIN info di ON r.donor_station_id = di.station_id
        LEFT JOIN info ri ON r.receiver_station_id = ri.station_id
        """
    )


# --------------------------------------------------------------------------- #
# Calidad y cobertura
# --------------------------------------------------------------------------- #
def rejection_breakdown() -> pd.DataFrame:
    return _q("SELECT reason AS motivo, COUNT(*) AS n FROM trip_rejections GROUP BY 1 ORDER BY 2 DESC")


def bridge_coverage() -> pd.DataFrame:
    return _q(
        "SELECT match_method AS metodo, COUNT(*) AS n, ROUND(AVG(confidence),3) AS confianza "
        "FROM station_bridge GROUP BY 1 ORDER BY 2 DESC"
    )


def gbfs_coverage() -> dict:
    df = _q(
        "SELECT COUNT(*) capturas, COUNT(DISTINCT station_id) estaciones, "
        "MIN(captured_at_local) tmin, MAX(captured_at_local) tmax FROM station_status"
    )
    if df.empty or int(df["capturas"].iloc[0]) == 0:
        return {"capturas": 0, "estaciones": 0, "tmin": None, "tmax": None}
    return {
        "capturas": int(df["capturas"].iloc[0]),
        "estaciones": int(df["estaciones"].iloc[0]),
        "tmin": df["tmin"].iloc[0],
        "tmax": df["tmax"].iloc[0],
    }
