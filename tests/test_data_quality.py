"""Pruebas de calidad de datos sobre la salida de limpieza."""

from __future__ import annotations

import pandas as pd

from transform.normalize_historical import clean_dataframe


def _raw_row(**kw):
    base = {
        "Genero_Usuario": "M",
        "Edad_Usuario": "30",
        "Bici": "0069",
        "Ciclo_Estacion_Retiro": "85",
        "Fecha_Retiro": "16/02/2010",
        "Hora_Retiro": "12:00:00",
        "Ciclo_EstacionArribo": "26",
        "Fecha_Arribo": "16/02/2010",
        "Hora_Arribo": "12:15:00",
    }
    base.update(kw)
    return base


def test_clean_sin_nulos_en_campos_clave():
    raw = pd.DataFrame([_raw_row() for _ in range(5)] + [_raw_row(Bici=str(i)) for i in range(5)])
    clean, _, _ = clean_dataframe(raw, "test.csv", "run1")
    for col in ["origin_station_id", "dest_station_id", "retiro_ts", "arribo_ts"]:
        assert clean[col].notna().all(), f"nulos en {col}"


def test_duraciones_dentro_de_limites():
    raw = pd.DataFrame([_raw_row(Bici=str(i)) for i in range(20)])
    clean, _, _ = clean_dataframe(raw, "test.csv", "run1")
    assert (clean["duration_min"] >= 1).all()
    assert (clean["duration_min"] <= 240).all()


def test_edad_float_se_convierte_a_entero():
    # Los archivos recientes traen edad como "41.0".
    raw = pd.DataFrame([_raw_row(Edad_Usuario="41.0", Bici="A"), _raw_row(Edad_Usuario="", Bici="B")])
    clean, _, _ = clean_dataframe(raw, "test.csv", "run1")
    edades = clean.set_index("bike_id")["edad"]
    assert edades["A"] == 41
    assert pd.isna(edades["B"])


def test_totales_cuadran():
    raw = pd.DataFrame([_raw_row(Bici=str(i)) for i in range(10)])
    clean, rej, report = clean_dataframe(raw, "test.csv", "run1")
    assert report["total"] == len(clean) + report["rechazadas"]
    assert report["validas"] == len(clean)
