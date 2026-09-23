"""Evaluación temporal: compara línea base vs modelo con honestidad.

Calcula MAE, RMSE, WAPE y sesgo medio sobre la partición de PRUEBA (y validación),
global y desagregado por estación, por hora, en horas pico y en las estaciones de
mayor demanda. Guarda tablas en reports/ y figuras en reports/figures/.

Si el modelo no supera a la línea base, se reporta tal cual (sin manipular datos).

Uso:
    python -m models.evaluate
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # backend sin ventana
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db import get_connection  # noqa: E402
from common.logging_utils import get_logger  # noqa: E402
from models.metrics import compute_all, metrics_by_group  # noqa: E402

logger = get_logger(__name__)

PEAK_HOURS = {7, 8, 9, 17, 18, 19, 20}
TOP_N_STATIONS = 10


def _overall(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, col in [("linea_base", "y_pred_baseline"), ("modelo", "y_pred_model")]:
        m = compute_all(df["y_true"].to_numpy(), df[col].to_numpy())
        m["modelo"] = name
        rows.append(m)
    return pd.DataFrame(rows)[["modelo", "mae", "rmse", "wape", "sesgo_medio", "n"]]


def evaluate() -> dict:
    settings = get_settings()
    con = get_connection()
    preds = con.execute("SELECT * FROM model_predictions").df()
    con.close()
    if preds.empty:
        logger.warning("No hay predicciones; entrena primero el modelo.")
        return {"status": "sin_datos"}

    reports_dir = settings.path("reports")
    figures_dir = settings.path("figures")
    reports_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    for split in ("val", "test"):
        d = preds[preds["split"] == split]
        if d.empty:
            continue
        overall = _overall(d)
        overall.insert(0, "split", split)
        overall.to_csv(reports_dir / f"metrics_overall_{split}.csv", index=False)
        results[split] = overall

    test = preds[preds["split"] == "test"].copy()
    if test.empty:
        logger.warning("Partición de prueba vacía.")
        return {"status": "sin_test"}

    test["hour"] = test["ts"].dt.hour

    # Por estación y por hora (para el modelo y la base).
    by_station = _by_group_compare(test, "station_id")
    by_hour = _by_group_compare(test, "hour")
    by_station.to_csv(reports_dir / "metrics_by_station.csv", index=False)
    by_hour.to_csv(reports_dir / "metrics_by_hour.csv", index=False)

    # Horas pico.
    peak = test[test["hour"].isin(PEAK_HOURS)]
    peak_overall = _overall(peak) if not peak.empty else pd.DataFrame()
    if not peak_overall.empty:
        peak_overall.insert(0, "segmento", "horas_pico")
        peak_overall.to_csv(reports_dir / "metrics_peak_hours.csv", index=False)

    # Estaciones de mayor demanda.
    top = (test.groupby("station_id")["y_true"].sum().sort_values(ascending=False)
           .head(TOP_N_STATIONS).index)
    top_df = test[test["station_id"].isin(top)]
    top_overall = _overall(top_df)
    top_overall.insert(0, "segmento", f"top_{TOP_N_STATIONS}_estaciones")
    top_overall.to_csv(reports_dir / "metrics_top_stations.csv", index=False)

    # --- Figuras ---
    _figure_overall(results.get("test"), figures_dir)
    _figure_by_hour(by_hour, figures_dir)

    # --- Comparación honesta ---
    ov = results.get("test")
    base_mae = float(ov.loc[ov["modelo"] == "linea_base", "mae"].iloc[0])
    model_mae = float(ov.loc[ov["modelo"] == "modelo", "mae"].iloc[0])
    mejora = round(100 * (base_mae - model_mae) / base_mae, 2) if base_mae else 0.0
    veredicto = (
        "el modelo SUPERA a la línea base" if model_mae < base_mae
        else "el modelo NO supera a la línea base"
    )
    logger.info("Test | MAE base=%.4f modelo=%.4f (mejora %.2f%%) => %s",
                base_mae, model_mae, mejora, veredicto)

    summary = {
        "mae_base": base_mae, "mae_modelo": model_mae,
        "mejora_pct": mejora, "veredicto": veredicto,
    }
    (reports_dir / "evaluation_summary.json").write_text(
        pd.Series(summary).to_json(indent=2), encoding="utf-8"
    )
    return {"status": "ok", **summary}


def _by_group_compare(df: pd.DataFrame, group: str) -> pd.DataFrame:
    base = metrics_by_group(df, "y_true", "y_pred_baseline", group).add_suffix("_base")
    model = metrics_by_group(df, "y_true", "y_pred_model", group).add_suffix("_modelo")
    base = base.rename(columns={f"{group}_base": group})
    model = model.rename(columns={f"{group}_modelo": group})
    return base.merge(model, on=group)


def _figure_overall(overall: pd.DataFrame | None, figures_dir) -> None:
    if overall is None or overall.empty:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(overall["modelo"], overall["mae"], color=["#888", "#2a7"])
    ax.set_title("MAE en prueba: línea base vs modelo")
    ax.set_ylabel("MAE (salidas/hora)")
    for i, v in enumerate(overall["mae"]):
        ax.text(i, v, f"{v:.3f}", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(figures_dir / "mae_baseline_vs_model.png", dpi=110)
    plt.close(fig)


def _figure_by_hour(by_hour: pd.DataFrame, figures_dir) -> None:
    if by_hour.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(by_hour["hour"], by_hour["mae_base"], marker="o", label="línea base")
    ax.plot(by_hour["hour"], by_hour["mae_modelo"], marker="s", label="modelo")
    ax.set_title("MAE por hora del día (prueba)")
    ax.set_xlabel("Hora")
    ax.set_ylabel("MAE")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "mae_by_hour.png", dpi=110)
    plt.close(fig)


def main() -> int:
    result = evaluate()
    logger.info("Evaluación: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
