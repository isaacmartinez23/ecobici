"""Algoritmo de recomendación de rebalanceo (heurístico, explicable).

Separado del modelo predictivo. Para una ventana operativa:

    1. Estima el inventario esperado por estación.
    2. Calcula un nivel mínimo de seguridad y un nivel objetivo.
    3. Identifica receptoras con déficit (inventario < seguridad).
    4. Identifica donantes con excedente (inventario > objetivo).
    5. Respeta la capacidad de las estaciones.
    6. No deja a una donante por debajo del nivel objetivo (>= seguridad).
    7. Empareja donantes y receptoras por cercanía (greedy).
    8. Calcula bicicletas por movimiento.
    9. Estima el déficit antes y después.
    10. Estima el porcentaje de desabasto evitado.

La recomendación es una ESTIMACIÓN, no un hecho.

Uso:
    python -m models.rebalance
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from common.config import get_settings
from common.db import get_connection, utcnow_naive
from common.geo import haversine_m
from common.logging_utils import get_logger

logger = get_logger(__name__)


def recommend_moves(
    stations: pd.DataFrame,
    safety_stock_fraction: float = 0.15,
    target_fill_fraction: float = 0.5,
    max_pair_distance_m: float = 1500.0,
    max_bikes_per_move: int = 20,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recomienda movimientos donante->receptora. Función pura y testeable.

    ``stations`` requiere: station_id, capacity, expected_inventory, lat, lon.
    Devuelve (movimientos, resumen). Garantiza:
    - bicis por movimiento > 0 (nunca negativas),
    - inventario total conservado,
    - ninguna receptora supera su capacidad,
    - ninguna donante queda por debajo del nivel objetivo.
    """
    s = stations.copy().reset_index(drop=True)
    s["capacity"] = s["capacity"].astype(float)
    s["inv"] = s["expected_inventory"].astype(float).clip(lower=0)
    s["inv"] = s[["inv", "capacity"]].min(axis=1)
    s["safety"] = (safety_stock_fraction * s["capacity"]).round()
    s["target"] = (target_fill_fraction * s["capacity"]).round()

    inv0 = s["inv"].sum()
    s["deficit_before"] = (s["safety"] - s["inv"]).clip(lower=0)

    # Necesidad (subir a objetivo) y disponibilidad (bajar solo hasta objetivo).
    s["need"] = (s["target"] - s["inv"]).clip(lower=0).round().astype(int)
    s["avail"] = (s["inv"] - s["target"]).clip(lower=0).apply(math.floor).astype(int)
    s["inv_after"] = s["inv"].copy()
    # Donantes disponibles ANTES de emparejar (s["avail"] se agota en el bucle).
    n_donors_initial = int((s["avail"] > 0).sum())

    receivers = s[s["deficit_before"] > 0].sort_values("deficit_before", ascending=False)
    moves: list[dict[str, Any]] = []

    for r_idx in receivers.index:
        while s.at[r_idx, "need"] > 0:
            # Donante más cercano con disponibilidad dentro del rango.
            best_d, best_dist = None, float("inf")
            for d_idx in s.index:
                if d_idx == r_idx or s.at[d_idx, "avail"] <= 0:
                    continue
                dist = haversine_m(
                    float(s.at[r_idx, "lat"]), float(s.at[r_idx, "lon"]),
                    float(s.at[d_idx, "lat"]), float(s.at[d_idx, "lon"]),
                )
                if dist <= max_pair_distance_m and dist < best_dist:
                    best_d, best_dist = d_idx, dist
            if best_d is None:
                break  # no hay donante alcanzable

            headroom = int(s.at[r_idx, "capacity"] - s.at[r_idx, "inv_after"])
            qty = min(
                int(s.at[r_idx, "need"]),
                int(s.at[best_d, "avail"]),
                int(max_bikes_per_move),
                headroom,
            )
            if qty <= 0:
                break

            donor_before = s.at[best_d, "inv_after"]
            recv_before = s.at[r_idx, "inv_after"]
            s.at[best_d, "inv_after"] = donor_before - qty
            s.at[r_idx, "inv_after"] = recv_before + qty
            s.at[best_d, "avail"] -= qty
            s.at[r_idx, "need"] -= qty

            moves.append(
                {
                    "donor_station_id": s.at[best_d, "station_id"],
                    "receiver_station_id": s.at[r_idx, "station_id"],
                    "bikes_to_move": int(qty),
                    "distance_m": round(best_dist, 1),
                    "donor_inventory_before": float(donor_before),
                    "donor_inventory_after": float(donor_before - qty),
                    "receiver_inventory_before": float(recv_before),
                    "receiver_inventory_after": float(recv_before + qty),
                    "confidence": round(max(0.0, 1.0 - best_dist / max_pair_distance_m), 3),
                }
            )

    s["deficit_after"] = (s["safety"] - s["inv_after"]).clip(lower=0)
    moves_df = pd.DataFrame(moves)

    # Enriquecer con déficit por receptora (antes/después).
    if not moves_df.empty:
        def_map_before = s.set_index("station_id")["deficit_before"]
        def_map_after = s.set_index("station_id")["deficit_after"]
        moves_df["receiver_deficit_before"] = moves_df["receiver_station_id"].map(def_map_before)
        moves_df["receiver_deficit_after"] = moves_df["receiver_station_id"].map(def_map_after)

    total_before = float(s["deficit_before"].sum())
    total_after = float(s["deficit_after"].sum())
    summary = {
        "estaciones": len(s),
        "receptoras": int((s["deficit_before"] > 0).sum()),
        "donantes_disponibles": n_donors_initial,
        "movimientos": len(moves_df),
        "bicis_movidas": int(moves_df["bikes_to_move"].sum()) if not moves_df.empty else 0,
        "deficit_antes": total_before,
        "deficit_despues": total_after,
        "pct_desabasto_evitado": round(100 * (total_before - total_after) / total_before, 2)
        if total_before > 0 else 0.0,
        "inventario_conservado": bool(abs(inv0 - s["inv_after"].sum()) < 1e-6),
    }
    return moves_df, summary


# --------------------------------------------------------------------------- #
# Integración con DuckDB
# --------------------------------------------------------------------------- #
def _expected_inventory(con, target_ts: pd.Timestamp, target_dow: int, target_hour: int) -> pd.DataFrame:
    """Inventario esperado por estación GBFS para la franja objetivo.

    Inventario esperado = inventario de referencia (captura más cercana a la hora
    objetivo) - flujo neto esperado (mediana histórica de salidas - llegadas por
    estación/día/hora, vía puente).
    """
    stations = con.execute(
        """
        SELECT station_id, capacity, lat, lon FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY captured_at_utc DESC) rn
            FROM station_information
        ) WHERE rn = 1
        """
    ).df()
    # Inventario de referencia: la captura más cercana en el tiempo a la hora objetivo.
    current = con.execute(
        """
        SELECT station_id, num_bikes_available AS current_inv FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY station_id
                ORDER BY abs(epoch(captured_at_local) - epoch(CAST(? AS TIMESTAMP))) ASC
            ) rn
            FROM station_status
        ) WHERE rn = 1
        """,
        [target_ts.to_pydatetime().replace(tzinfo=None)],
    ).df()

    # Flujo neto esperado (mediana histórica) mapeado a la estación GBFS.
    flow = con.execute(
        """
        WITH med AS (
            SELECT d.station_id AS historico_id,
                   median(d.salidas) AS med_salidas,
                   median(d.llegadas) AS med_llegadas
            FROM demand_hourly d
            WHERE d.dow = ? AND d.hour = ?
            GROUP BY d.station_id
        )
        SELECT b.gbfs_id AS station_id,
               COALESCE(m.med_salidas, 0) AS med_salidas,
               COALESCE(m.med_llegadas, 0) AS med_llegadas
        FROM station_bridge b
        LEFT JOIN med m ON b.historico_id = m.historico_id
        WHERE b.gbfs_id IS NOT NULL
        """,
        [target_dow, target_hour],
    ).df()

    df = stations.merge(current, on="station_id", how="left").merge(
        flow, on="station_id", how="left"
    )
    df["current_inv"] = df["current_inv"].fillna(df["capacity"] * 0.5)
    df["med_salidas"] = df["med_salidas"].fillna(0)
    df["med_llegadas"] = df["med_llegadas"].fillna(0)
    df["expected_inventory"] = (
        df["current_inv"] - (df["med_salidas"] - df["med_llegadas"])
    ).clip(lower=0)
    return df


def build_recommendations(target_ts: pd.Timestamp | None = None) -> dict[str, Any]:
    settings = get_settings()
    rb = settings.get("rebalance", default={})
    con = get_connection()

    last_status = con.execute("SELECT max(captured_at_local) FROM station_status").fetchone()[0]
    if last_status is None:
        logger.warning("Sin capturas GBFS; no se puede estimar inventario.")
        con.close()
        return {"status": "sin_gbfs"}
    if target_ts is None:
        # Hora pico vespertina del último día capturado (mayor dispersión de inventario).
        target_ts = pd.Timestamp(last_status).normalize() + pd.Timedelta(hours=18)
    target_dow = (target_ts.weekday())  # 0=lunes
    target_hour = int(target_ts.hour)

    stations = _expected_inventory(con, target_ts, target_dow, target_hour)
    moves, summary = recommend_moves(
        stations,
        safety_stock_fraction=float(rb.get("safety_stock_fraction", 0.15)),
        target_fill_fraction=float(rb.get("target_fill_fraction", 0.5)),
        max_pair_distance_m=float(rb.get("max_pair_distance_m", 1500.0)),
        max_bikes_per_move=int(rb.get("max_bikes_per_move", 20)),
    )

    model_version = "rebalanceo_heuristico_v1"
    con.execute("DELETE FROM rebalance_recommendations")
    if not moves.empty:
        moves = moves.copy()
        moves["target_ts"] = target_ts.to_pydatetime().replace(tzinfo=None)
        moves["model_version"] = model_version
        moves["created_at_utc"] = utcnow_naive()
        cols = [
            "target_ts", "donor_station_id", "receiver_station_id", "bikes_to_move",
            "distance_m", "donor_inventory_before", "donor_inventory_after",
            "receiver_inventory_before", "receiver_inventory_after",
            "receiver_deficit_before", "receiver_deficit_after", "confidence",
            "model_version", "created_at_utc",
        ]
        con.register("tmp_moves", moves[cols])
        con.execute(f"INSERT INTO rebalance_recommendations SELECT {', '.join(cols)} FROM tmp_moves")
        con.unregister("tmp_moves")
    con.close()

    summary["target_ts"] = str(target_ts)
    logger.info("Rebalanceo %s | %s", target_ts, summary)
    return {"status": "ok", **summary}


def main() -> int:
    build_recommendations()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
