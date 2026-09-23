"""Línea base estadística por medianas históricas.

Predice la demanda (salidas) por estación y franja con una jerarquía de
respaldos, todos calculados SOLO con datos de entrenamiento:

    1. Mediana por (estación, día de semana, hora).
    2. Respaldo: mediana por (estación, hora).
    3. Respaldo: mediana global por hora.
    4. Último respaldo: mediana global.

Es intencionalmente simple y transparente: el modelo supervisado debe superarla
para justificar su complejidad.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BaselineModel:
    """Tablas de mediana para la predicción base."""

    by_station_dow_hour: pd.Series
    by_station_hour: pd.Series
    by_hour: pd.Series
    global_median: float
    target: str = "salidas"


def fit_baseline(train: pd.DataFrame, target: str = "salidas") -> BaselineModel:
    """Ajusta las tablas de mediana usando exclusivamente datos de entrenamiento."""
    req = {"station_id", "dow", "hour", target}
    missing = req - set(train.columns)
    if missing:
        raise ValueError(f"Faltan columnas para la línea base: {missing}")
    return BaselineModel(
        by_station_dow_hour=train.groupby(["station_id", "dow", "hour"])[target].median(),
        by_station_hour=train.groupby(["station_id", "hour"])[target].median(),
        by_hour=train.groupby(["hour"])[target].median(),
        global_median=float(train[target].median()),
        target=target,
    )


def predict_baseline(model: BaselineModel, df: pd.DataFrame) -> pd.Series:
    """Predice con la jerarquía de respaldos. Devuelve una Serie alineada a df."""
    sdh = model.by_station_dow_hour
    sh = model.by_station_hour
    h = model.by_hour

    def _lookup(row) -> float:
        key3 = (row["station_id"], row["dow"], row["hour"])
        if key3 in sdh.index:
            return float(sdh.loc[key3])
        key2 = (row["station_id"], row["hour"])
        if key2 in sh.index:
            return float(sh.loc[key2])
        if row["hour"] in h.index:
            return float(h.loc[row["hour"]])
        return model.global_median

    return df.apply(_lookup, axis=1).astype(float)
