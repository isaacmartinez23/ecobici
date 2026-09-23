"""Pruebas de parsing y normalización del histórico (sin fuga de día/mes)."""

from __future__ import annotations

import pandas as pd

from transform.normalize_historical import (
    REASON_ARRIVAL_NOT_AFTER,
    REASON_DUPLICATE,
    REASON_INVALID_DATETIME,
    REASON_MISSING_DEST,
    REASON_MISSING_ORIGIN,
    REASON_TOO_LONG,
    REASON_TOO_SHORT,
    clean_dataframe,
)
from transform.parsing import normalize_columns, parse_datetime_series, to_snake_case

DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M", "%H:%M:%S.%f"]


def test_snake_case_variantes():
    # Variante real 2025/2026 sin guion antes de "Arribo".
    assert to_snake_case("Ciclo_EstacionArribo") == "ciclo_estacion_arribo"
    assert to_snake_case("Ciclo_Estacion_Arribo") == "ciclo_estacion_arribo"
    assert to_snake_case("Género_Usuario") == "genero_usuario"
    assert to_snake_case("Fecha_Retiro") == "fecha_retiro"


def test_normalize_columns_unifica_variantes():
    df = pd.DataFrame(columns=["Género_Usuario", "Ciclo_EstacionArribo", "Fecha_Retiro"])
    out = normalize_columns(df)
    assert "genero_usuario" in out.columns
    assert "ciclo_estacion_arribo" in out.columns


def test_parse_fechas_dos_formatos():
    fecha = pd.Series(["2010-02-16", "31/07/2026"])
    hora = pd.Series(["12:42:32.160000", "23:22:23"])
    ts = parse_datetime_series(fecha, hora, DATE_FORMATS, TIME_FORMATS)
    assert ts.iloc[0].year == 2010 and ts.iloc[0].microsecond == 160000
    assert ts.iloc[1].year == 2026 and ts.iloc[1].month == 7 and ts.iloc[1].day == 31


def test_no_intercambia_dia_mes():
    # 31/12/2024 solo es válido como d/m/Y; 05/06 debe ser 5 de junio (no 6 de mayo).
    fecha = pd.Series(["31/12/2024", "05/06/2025"])
    hora = pd.Series(["23:57:02", "10:00:00"])
    ts = parse_datetime_series(fecha, hora, DATE_FORMATS, TIME_FORMATS)
    assert ts.iloc[0].month == 12 and ts.iloc[0].day == 31
    assert ts.iloc[1].month == 6 and ts.iloc[1].day == 5


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


def test_reglas_de_rechazo():
    rows = [
        _raw_row(),  # válida (15 min)
        _raw_row(Hora_Arribo="12:00:30"),  # muy corta (<1 min)
        _raw_row(Hora_Arribo="17:00:00"),  # muy larga (>240 min)
        _raw_row(Hora_Arribo="11:00:00"),  # arribo antes del retiro
        _raw_row(Ciclo_Estacion_Retiro=""),  # origen ausente
        _raw_row(Ciclo_EstacionArribo=""),  # destino ausente
        _raw_row(Fecha_Retiro="fecha-mala"),  # fecha inválida
    ]
    raw = pd.DataFrame(rows)
    clean, rej, report = clean_dataframe(raw, "test.csv", "run1")
    motivos = set(rej["reason"])
    assert REASON_TOO_SHORT in motivos
    assert REASON_TOO_LONG in motivos
    assert REASON_ARRIVAL_NOT_AFTER in motivos
    assert REASON_MISSING_ORIGIN in motivos
    assert REASON_MISSING_DEST in motivos
    assert REASON_INVALID_DATETIME in motivos
    assert report["validas"] == 1
    assert report["total"] == 7


def test_deteccion_duplicados():
    raw = pd.DataFrame([_raw_row(), _raw_row(), _raw_row(Bici="0070")])
    clean, rej, report = clean_dataframe(raw, "test.csv", "run1")
    # Dos filas idénticas: una válida, la otra 'duplicado'. La tercera difiere.
    assert (rej["reason"] == REASON_DUPLICATE).sum() == 1
    assert report["validas"] == 2


def test_reporte_porcentaje():
    raw = pd.DataFrame([_raw_row(), _raw_row(Hora_Arribo="12:00:30")])
    _, _, report = clean_dataframe(raw, "test.csv", "run1")
    assert report["pct_rechazado"] == 50.0
