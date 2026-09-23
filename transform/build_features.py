"""Construcción de variables predictivas por estación y hora, sin fuga temporal.

Regla central: TODA variable rezagada o móvil usa exclusivamente información
disponible ANTES de la hora predicha. Esto se garantiza aplicando ``shift(1)``
por estación antes de cualquier ventana móvil, de modo que el valor de la hora t
nunca entra en sus propias features.

Uso:
    python -m transform.build_features
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from common.config import get_settings
from common.db import get_connection
from common.logging_utils import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Festivos oficiales de México (sin dependencias externas).
# --------------------------------------------------------------------------- #
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-ésimo 'weekday' (0=lunes) del mes."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def mexican_holidays(years: list[int]) -> set[date]:
    """Días festivos oficiales (Ley Federal del Trabajo, reglas de fecha fija/lunes)."""
    days: set[date] = set()
    for y in years:
        days.update(
            {
                date(y, 1, 1),  # Año nuevo
                _nth_weekday(y, 2, 0, 1),  # 1er lunes de febrero (Constitución)
                _nth_weekday(y, 3, 0, 3),  # 3er lunes de marzo (Benito Juárez)
                date(y, 5, 1),  # Día del trabajo
                date(y, 9, 16),  # Independencia
                _nth_weekday(y, 11, 0, 3),  # 3er lunes de noviembre (Revolución)
                date(y, 12, 25),  # Navidad
            }
        )
    return days


def _is_quincena(d: pd.Timestamp) -> bool:
    """Quincena: día 15 o último día del mes (aprox. días de pago)."""
    last_day = (d + pd.offsets.MonthEnd(0)).day
    return d.day == 15 or d.day == last_day


# --------------------------------------------------------------------------- #
# Construcción de features
# --------------------------------------------------------------------------- #
def _station_meta(con) -> pd.DataFrame:
    """Capacidad/lat/lon por estación histórica vía puente -> station_information."""
    df = con.execute(
        """
        SELECT b.historico_id AS station_id, si.capacity, si.lat, si.lon
        FROM station_bridge b
        LEFT JOIN (
            SELECT station_id, capacity, lat, lon,
                   ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
            FROM station_information
        ) si ON b.gbfs_id = si.station_id AND si.rn = 1
        """
    ).df()
    return df


def _availability_lagged(con) -> pd.DataFrame:
    """bikes_end por estación-hora, para exponer disponibilidad reciente."""
    df = con.execute(
        """
        SELECT station_id,
               (CAST(date AS TIMESTAMP) + (hour * INTERVAL 1 HOUR)) AS ts,
               bikes_end
        FROM availability_hourly
        """
    ).df()
    return df


def build_feature_frame(demand: pd.DataFrame, meta: pd.DataFrame, avail: pd.DataFrame,
                        lag_hours: list[int], rolling_windows: list[int]) -> pd.DataFrame:
    """Construye el frame de features denso y sin fuga. Función testeable."""
    if demand.empty:
        return pd.DataFrame()
    demand = demand.copy()
    demand["ts"] = pd.to_datetime(demand["date"]) + pd.to_timedelta(demand["hour"], unit="h")

    # --- Rejilla densa estación x hora (rellena horas sin actividad con 0) ---
    full_range = pd.date_range(demand["ts"].min(), demand["ts"].max(), freq="h")
    stations = demand["station_id"].unique()
    grid = pd.MultiIndex.from_product([stations, full_range], names=["station_id", "ts"]).to_frame(index=False)
    df = grid.merge(demand[["station_id", "ts", "salidas", "llegadas", "flujo_neto"]],
                    on=["station_id", "ts"], how="left")
    for c in ("salidas", "llegadas", "flujo_neto"):
        df[c] = df[c].fillna(0.0)
    df = df.sort_values(["station_id", "ts"]).reset_index(drop=True)

    # --- Variables de calendario ---
    ts = df["ts"]
    df["hour"] = ts.dt.hour
    df["dow"] = ts.dt.weekday
    df["is_weekend"] = df["dow"] >= 5
    df["month"] = ts.dt.month
    df["week"] = ts.dt.isocalendar().week.astype(int)
    years = sorted(ts.dt.year.unique().tolist())
    holidays = mexican_holidays(years)
    df["is_holiday"] = ts.dt.date.isin(holidays)
    df["quincena"] = ts.map(_is_quincena)

    # --- Metadatos de estación ---
    df = df.merge(meta, on="station_id", how="left")

    # --- Disponibilidad reciente (rezagada 1 hora, sin fuga) ---
    if not avail.empty:
        avail = avail.copy()
        avail["ts"] = pd.to_datetime(avail["ts"])
        df = df.merge(avail, on=["station_id", "ts"], how="left")
        df["bikes_end_lag_1"] = df.groupby("station_id")["bikes_end"].shift(1)
        df = df.drop(columns=["bikes_end"])
    else:
        df["bikes_end_lag_1"] = pd.NA

    # --- Rezagos y ventanas móviles SOBRE EL OBJETIVO (shift(1) => sin fuga) ---
    g = df.groupby("station_id")["salidas"]
    for lag in lag_hours:
        df[f"salidas_lag_{lag}"] = g.shift(lag)
    shifted = g.shift(1)  # excluye la hora actual
    for w in rolling_windows:
        roll = shifted.groupby(df["station_id"]).rolling(window=w, min_periods=1)
        df[f"salidas_roll_mean_{w}"] = roll.mean().reset_index(level=0, drop=True)
        df[f"salidas_roll_median_{w}"] = roll.median().reset_index(level=0, drop=True)

    return df


def build() -> dict[str, int]:
    settings = get_settings()
    con = get_connection()
    demand = con.execute("SELECT station_id, date, hour, salidas, llegadas, flujo_neto FROM demand_hourly").df()
    meta = _station_meta(con)
    avail = _availability_lagged(con)
    lag_hours = list(settings.get("features", "lag_hours", default=[1, 2, 24, 168]))
    rolling = list(settings.get("features", "rolling_windows_hours", default=[3, 24, 168]))

    df = build_feature_frame(demand, meta, avail, lag_hours, rolling)
    if df.empty:
        logger.warning("Sin demanda para construir features.")
        con.close()
        return {"model_features": 0}

    con.register("tmp_feat", df)
    con.execute("CREATE OR REPLACE TABLE model_features AS SELECT * FROM tmp_feat")
    con.unregister("tmp_feat")

    out = settings.path("processed") / "model_features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    n = len(df)
    con.close()
    logger.info("model_features: %d filas, %d columnas -> %s", n, df.shape[1], out.name)
    return {"model_features": n}


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
