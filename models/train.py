"""Entrenamiento del modelo de demanda con partición estrictamente temporal.

Objetivo por defecto: ``salidas`` (demanda atendida de retiro) por estación-hora.
La partición es temporal (nunca aleatoria): los primeros periodos entrenan, el
penúltimo valida y el último prueba. Las fechas se derivan de los datos.

Usa LightGBM si está disponible; de lo contrario, HistGradientBoostingRegressor
de scikit-learn (ambos toleran NaN en los rezagos iniciales).

Uso:
    python -m models.train
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from common.config import get_settings
from common.db import get_connection, utcnow_naive
from common.logging_utils import get_logger
from models.baseline import fit_baseline, predict_baseline

logger = get_logger(__name__)

# Columnas que NO son features (objetivo y contemporáneas => fuga).
_NON_FEATURES = {"ts", "salidas", "llegadas", "flujo_neto", "station_id"}


@dataclass
class SplitBoundaries:
    val_start: pd.Timestamp
    test_start: pd.Timestamp


def temporal_split(df: pd.DataFrame, val_q: float = 0.6, test_q: float = 0.8) -> SplitBoundaries:
    """Calcula fronteras temporales por cuantiles del timestamp (sin azar)."""
    ts_sorted = df["ts"].sort_values()
    return SplitBoundaries(
        val_start=ts_sorted.quantile(val_q),
        test_start=ts_sorted.quantile(test_q),
    )


def assign_split(df: pd.DataFrame, bounds: SplitBoundaries) -> pd.Series:
    split = pd.Series("train", index=df.index)
    split[df["ts"] >= bounds.val_start] = "val"
    split[df["ts"] >= bounds.test_start] = "test"
    return split


def _feature_matrix(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    X = df[feature_cols].copy()
    for c in X.columns:
        if X[c].dtype == bool:
            X[c] = X[c].astype(int)
    return X


def _build_model():
    """Devuelve (modelo, nombre). Prefiere LightGBM; respaldo sklearn."""
    seed = get_settings().random_seed
    try:
        from lightgbm import LGBMRegressor

        model = LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            subsample=0.9, colsample_bytree=0.9, random_state=seed, n_jobs=-1,
            verbose=-1,
        )
        return model, "lightgbm"
    except Exception as exc:  # noqa: BLE001
        logger.warning("LightGBM no disponible (%s); uso HistGradientBoosting.", exc)
        from sklearn.ensemble import HistGradientBoostingRegressor

        model = HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.05, random_state=seed
        )
        return model, "hist_gbr"


def train(target: str | None = None) -> dict:
    settings = get_settings()
    target = target or settings.get("model", "target", default="salidas")
    con = get_connection()
    df = con.execute("SELECT * FROM model_features").df()
    if df.empty:
        logger.warning("model_features vacío; entrena primero las features.")
        con.close()
        return {"status": "sin_datos"}

    df = df.sort_values(["ts", "station_id"]).reset_index(drop=True)
    df["station_code"] = df["station_id"].astype("category").cat.codes

    feature_cols = [c for c in df.columns if c not in _NON_FEATURES and c != target]
    feature_cols = [c for c in feature_cols if df[c].dtype.kind in "biufc"]

    bounds = temporal_split(df)
    df["split"] = assign_split(df, bounds)
    train_df = df[df["split"] == "train"]
    logger.info(
        "Partición temporal | train=%d val=%d test=%d | val>=%s test>=%s",
        (df["split"] == "train").sum(), (df["split"] == "val").sum(),
        (df["split"] == "test").sum(), bounds.val_start, bounds.test_start,
    )

    # --- Línea base (ajustada solo con train) ---
    baseline = fit_baseline(train_df, target=target)
    df["y_pred_baseline"] = predict_baseline(baseline, df)

    # --- Modelo supervisado ---
    model, model_name = _build_model()
    X_train = _feature_matrix(train_df, feature_cols)
    y_train = train_df[target].to_numpy()
    model.fit(X_train, y_train)
    X_all = _feature_matrix(df, feature_cols)
    df["y_pred_model"] = np.clip(model.predict(X_all), 0, None)

    model_version = f"{model_name}_{utcnow_naive().strftime('%Y%m%dT%H%M%S')}"

    # --- Persistencia de predicciones (todas las particiones) ---
    preds = pd.DataFrame(
        {
            "station_id": df["station_id"],
            "ts": df["ts"],
            "target": target,
            "y_true": df[target].astype(float),
            "y_pred_baseline": df["y_pred_baseline"].astype(float),
            "y_pred_model": df["y_pred_model"].astype(float),
            "split": df["split"],
            "model_version": model_version,
            "created_at_utc": utcnow_naive(),
        }
    )
    con.execute("DELETE FROM model_predictions WHERE target = ?", [target])
    con.register("tmp_preds", preds)
    con.execute("INSERT INTO model_predictions SELECT * FROM tmp_preds")
    con.unregister("tmp_preds")
    con.close()

    # --- Guarda artefacto del modelo ---
    import joblib

    art_dir = settings.path("models_artifacts")
    art_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, art_dir / "model.joblib")
    meta = {
        "model_version": model_version,
        "model_name": model_name,
        "target": target,
        "feature_cols": feature_cols,
        "val_start": str(bounds.val_start),
        "test_start": str(bounds.test_start),
    }
    (art_dir / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("Modelo entrenado (%s) y guardado en %s", model_version, art_dir)
    return {"status": "ok", "model_version": model_version, "n_features": len(feature_cols)}


def main() -> int:
    result = train()
    logger.info("Entrenamiento: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
