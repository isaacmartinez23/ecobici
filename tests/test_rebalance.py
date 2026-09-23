"""Pruebas del rebalanceo: capacidad, conservación, no-negatividad, sin donantes."""

from __future__ import annotations

import pandas as pd

from models.rebalance import recommend_moves


def _stations(inv: list[int], cap: int = 20, spread: float = 0.001) -> pd.DataFrame:
    """Estaciones colineales muy cercanas (para no chocar con la distancia)."""
    n = len(inv)
    return pd.DataFrame(
        {
            "station_id": [str(i) for i in range(n)],
            "capacity": [cap] * n,
            "expected_inventory": inv,
            "lat": [19.4 + i * spread for i in range(n)],
            "lon": [-99.1] * n,
        }
    )


def test_mueve_de_donante_a_receptora():
    # Estación 0 vacía (receptora), estación 1 llena (donante).
    s = _stations([0, 20], cap=20)
    moves, summary = recommend_moves(s, safety_stock_fraction=0.15, target_fill_fraction=0.5)
    assert summary["movimientos"] >= 1
    assert summary["bicis_movidas"] > 0
    assert (moves["donor_station_id"] == "1").all()
    assert (moves["receiver_station_id"] == "0").all()


def test_inventario_se_conserva():
    s = _stations([0, 2, 20, 18], cap=20)
    _, summary = recommend_moves(s)
    assert summary["inventario_conservado"] is True


def test_capacidad_respetada():
    # Receptora casi llena: no debe superar la capacidad.
    s = _stations([19, 20], cap=20)
    moves, _ = recommend_moves(s)
    if not moves.empty:
        assert (moves["receiver_inventory_after"] <= 20).all()


def test_donante_no_baja_de_seguridad():
    s = _stations([0, 20], cap=20)
    moves, _ = recommend_moves(s, safety_stock_fraction=0.15, target_fill_fraction=0.5)
    safety = 0.15 * 20
    # El inventario final de la donante nunca cae por debajo de seguridad.
    assert (moves["donor_inventory_after"] >= safety).all()


def test_nunca_mueve_cantidades_negativas():
    s = _stations([0, 5, 20, 20], cap=20)
    moves, _ = recommend_moves(s)
    assert (moves["bikes_to_move"] > 0).all()


def test_sin_donantes_no_hay_movimientos():
    # Todas por debajo del objetivo: no hay excedente que donar.
    s = _stations([0, 1, 2, 3], cap=20)
    moves, summary = recommend_moves(s)
    assert summary["movimientos"] == 0
    assert summary["deficit_despues"] == summary["deficit_antes"]


def test_distancia_maxima_bloquea_movimiento():
    # Donante llena pero lejísimos: no debe emparejarse.
    s = pd.DataFrame(
        {
            "station_id": ["0", "1"],
            "capacity": [20, 20],
            "expected_inventory": [0, 20],
            "lat": [19.40, 19.80],  # ~44 km de separación
            "lon": [-99.10, -99.10],
        }
    )
    moves, summary = recommend_moves(s, max_pair_distance_m=1500.0)
    assert summary["movimientos"] == 0


def test_no_negatividad_en_inventario_esperado_negativo():
    # Inventario esperado negativo se trata como 0 (no rompe la conservación).
    s = _stations([-5, 20], cap=20)
    moves, summary = recommend_moves(s)
    assert summary["inventario_conservado"] is True
    if not moves.empty:
        assert (moves["bikes_to_move"] > 0).all()
