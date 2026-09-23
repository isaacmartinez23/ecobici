"""Pruebas del puente de estaciones: métodos de emparejamiento."""

from __future__ import annotations

import pandas as pd

from transform.build_station_bridge import match_stations, normalize_name


def test_normalize_name():
    assert normalize_name("Reforma - Insurgentes") == "reforma insurgentes"
    assert normalize_name("MÉTRO Balderas") == "metro balderas"
    assert normalize_name(None) == ""


def _gbfs():
    return pd.DataFrame(
        {
            "gbfs_id": ["1", "2", "3"],
            "nombre": ["Reforma Insurgentes", "Metro Balderas", "Parque Mexico"],
            "lat": [19.427, 19.427, 19.412],
            "lon": [-99.167, -99.145, -99.170],
        }
    )


def test_match_exacto_por_id():
    hist = pd.DataFrame({"historico_id": ["2"], "nombre": [None], "lat": [None], "lon": [None]})
    bridge = match_stations(hist, _gbfs())
    assert bridge.iloc[0]["match_method"] == "exact_id"
    assert bridge.iloc[0]["gbfs_id"] == "2"


def test_match_nombre_normalizado():
    hist = pd.DataFrame({"historico_id": ["99"], "nombre": ["MÉTRO  Balderas"], "lat": [None], "lon": [None]})
    bridge = match_stations(hist, _gbfs())
    assert bridge.iloc[0]["match_method"] == "norm_name"
    assert bridge.iloc[0]["gbfs_id"] == "2"


def test_match_fuzzy():
    hist = pd.DataFrame({"historico_id": ["98"], "nombre": ["Reforma Insurgentez"], "lat": [None], "lon": [None]})
    bridge = match_stations(hist, _gbfs(), min_name_similarity=0.8)
    assert bridge.iloc[0]["match_method"] == "fuzzy_name"
    assert bridge.iloc[0]["gbfs_id"] == "1"


def test_match_geografico():
    # Sin nombre ni id coincidente, pero coordenadas casi idénticas a la estación 3.
    hist = pd.DataFrame({"historico_id": ["97"], "nombre": [None], "lat": [19.4121], "lon": [-99.1701]})
    bridge = match_stations(hist, _gbfs(), max_match_distance_m=200.0)
    assert bridge.iloc[0]["match_method"] == "geo"
    assert bridge.iloc[0]["gbfs_id"] == "3"
    assert bridge.iloc[0]["distance_m"] < 200


def test_sin_emparejar():
    hist = pd.DataFrame({"historico_id": ["500"], "nombre": ["Estación Fantasma"], "lat": [None], "lon": [None]})
    bridge = match_stations(hist, _gbfs())
    assert bridge.iloc[0]["match_method"] == "unmatched"
    assert pd.isna(bridge.iloc[0]["gbfs_id"])


def test_alias_manual_tiene_prioridad():
    hist = pd.DataFrame({"historico_id": ["1"], "nombre": [None], "lat": [None], "lon": [None]})
    # Alias fuerza 1 -> 3 aunque exista id exacto 1.
    bridge = match_stations(hist, _gbfs(), aliases={"1": "3"})
    assert bridge.iloc[0]["match_method"] == "manual_alias"
    assert bridge.iloc[0]["gbfs_id"] == "3"
