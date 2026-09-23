"""Pruebas de features: ausencia de fuga temporal en rezagos y ventanas móviles."""

from __future__ import annotations

import numpy as np
import pandas as pd

from transform.build_features import build_feature_frame, mexican_holidays


def _demand_lineal(n_horas: int = 30) -> pd.DataFrame:
    """Una estación con salidas = 0,1,2,... en horas consecutivas."""
    start = pd.Timestamp("2025-06-01 00:00:00")
    rows = []
    for i in range(n_horas):
        ts = start + pd.Timedelta(hours=i)
        rows.append(
            {
                "station_id": "1",
                "date": ts.date(),
                "hour": ts.hour,
                "salidas": float(i),
                "llegadas": 0.0,
                "flujo_neto": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_lag_1_es_valor_previo():
    demand = _demand_lineal()
    meta = pd.DataFrame({"station_id": ["1"], "capacity": [20], "lat": [19.4], "lon": [-99.1]})
    df = build_feature_frame(demand, meta, pd.DataFrame(), [1, 2], [3])
    df = df.sort_values("ts").reset_index(drop=True)
    # salidas_lag_1[i] debe ser salidas[i-1].
    for i in range(1, len(df)):
        assert df.loc[i, "salidas_lag_1"] == df.loc[i - 1, "salidas"]


def test_rolling_no_incluye_hora_actual():
    demand = _demand_lineal()
    meta = pd.DataFrame({"station_id": ["1"], "capacity": [20], "lat": [19.4], "lon": [-99.1]})
    df = build_feature_frame(demand, meta, pd.DataFrame(), [1], [3])
    df = df.sort_values("ts").reset_index(drop=True)
    # roll_mean_3 en i = media de salidas[i-3:i] (excluye i). Con salidas=i:
    # para i>=3 => media(i-3,i-2,i-1) = i-2.
    for i in range(3, len(df)):
        esperado = np.mean([i - 3, i - 2, i - 1])
        assert abs(df.loc[i, "salidas_roll_mean_3"] - esperado) < 1e-9
        # Nunca debe igualar una media que incluya el valor actual (i).
        media_con_actual = np.mean([i - 2, i - 1, i])
        assert abs(df.loc[i, "salidas_roll_mean_3"] - media_con_actual) > 1e-9


def test_primeras_filas_lag_son_nan():
    demand = _demand_lineal()
    meta = pd.DataFrame({"station_id": ["1"], "capacity": [20], "lat": [19.4], "lon": [-99.1]})
    df = build_feature_frame(demand, meta, pd.DataFrame(), [2], [3]).sort_values("ts").reset_index(drop=True)
    assert pd.isna(df.loc[0, "salidas_lag_2"])
    assert pd.isna(df.loc[1, "salidas_lag_2"])
    assert df.loc[2, "salidas_lag_2"] == df.loc[0, "salidas"]


def test_festivos_mexico():
    hol = mexican_holidays([2025])
    import datetime as dt
    assert dt.date(2025, 9, 16) in hol  # Independencia
    assert dt.date(2025, 5, 1) in hol   # Trabajo
    assert dt.date(2025, 2, 3) in hol   # 1er lunes de febrero
    assert dt.date(2025, 7, 4) not in hol
