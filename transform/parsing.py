"""Parsing robusto y normalización de esquema del histórico de ECOBICI.

Funciones puras (sin DB) para facilitar las pruebas. El histórico cambia de
esquema entre años (p. ej. ``Ciclo_Estacion_Arribo`` vs ``Ciclo_EstacionArribo``,
fechas ``%Y-%m-%d`` vs ``%d/%m/%Y``), por lo que:

- La normalización de columnas usa snake_case + un mapa de sinónimos.
- El parsing de fechas prueba explícitamente una lista documentada de formatos;
  no hay inferencia silenciosa que pueda intercambiar día y mes.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Columnas canónicas esperadas tras la normalización.
CANONICAL_COLUMNS = [
    "genero_usuario",
    "edad_usuario",
    "bici",
    "ciclo_estacion_retiro",
    "fecha_retiro",
    "hora_retiro",
    "ciclo_estacion_arribo",
    "fecha_arribo",
    "hora_arribo",
]

# Sinónimos conocidos -> nombre canónico (claves ya en snake_case).
_SYNONYMS: dict[str, str] = {
    "genero": "genero_usuario",
    "sexo": "genero_usuario",
    "edad": "edad_usuario",
    "bici": "bici",
    "id_bici": "bici",
    "bike_id": "bici",
    "ciclo_estacion_retiro": "ciclo_estacion_retiro",
    "estacion_retiro": "ciclo_estacion_retiro",
    "ciclo_estacion_arribo": "ciclo_estacion_arribo",
    "estacion_arribo": "ciclo_estacion_arribo",
    "fecha_retiro": "fecha_retiro",
    "hora_retiro": "hora_retiro",
    "fecha_arribo": "fecha_arribo",
    "hora_arribo": "hora_arribo",
}


def to_snake_case(name: str) -> str:
    """Convierte un nombre de columna a snake_case, sin acentos.

    Inserta guiones bajos en los límites camelCase, de modo que
    ``Ciclo_EstacionArribo`` -> ``ciclo_estacion_arribo``.
    """
    # Quita acentos.
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # Inserta _ entre minúscula/dígito y mayúscula (camelCase).
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    # Sustituye separadores no alfanuméricos por _.
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name.lower()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra columnas a la forma canónica usando snake_case + sinónimos."""
    rename: dict[str, str] = {}
    for col in df.columns:
        snake = to_snake_case(str(col))
        rename[col] = _SYNONYMS.get(snake, snake)
    out = df.rename(columns=rename)
    # Si hay columnas duplicadas tras el renombrado, conserva la primera.
    out = out.loc[:, ~out.columns.duplicated()]
    return out


def parse_datetime_series(
    date_ser: pd.Series,
    time_ser: pd.Series,
    date_formats: list[str],
    time_formats: list[str],
) -> pd.Series:
    """Parsea fecha+hora probando combinaciones explícitas de formato.

    Devuelve una Serie de datetime64 (NaT donde ninguna combinación aplica).
    Rellena progresivamente: cada combinación solo actúa sobre los aún-NaT.
    """
    date_str = date_ser.astype("string").str.strip()
    time_str = time_ser.astype("string").str.strip()
    combined = date_str.fillna("") + " " + time_str.fillna("")
    result = pd.Series(pd.NaT, index=combined.index, dtype="datetime64[ns]")
    for dfmt in date_formats:
        for tfmt in time_formats:
            pending = result.isna() & date_str.notna() & time_str.notna()
            if not pending.any():
                return result
            parsed = pd.to_datetime(
                combined[pending], format=f"{dfmt} {tfmt}", errors="coerce"
            )
            result.loc[pending] = parsed
    return result


def coerce_age(series: pd.Series) -> pd.Series:
    """Convierte edad a Int64 nullable (tolera '41', '41.0', '', 'nan')."""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.round().astype("Int64")


def clean_station_id(series: pd.Series) -> pd.Series:
    """Normaliza IDs de estación: string sin ceros a la izquierda espurios.

    Trata '', 'nan', 'null', 'none' como ausentes (pd.NA). Conserva el valor
    tal cual en otro caso (los IDs pueden ser numéricos o alfanuméricos).
    """
    s = series.astype("string").str.strip()
    missing = s.str.lower().isin(["", "nan", "null", "none"]) | s.isna()
    s = s.mask(missing, pd.NA)
    return s
