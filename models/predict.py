"""Predicción con el modelo entrenado.

Carga el artefacto (`models/artifacts/model.joblib` + `model_meta.json`) y predice
la demanda (salidas) para un conjunto de features. Incluye un atajo para predecir
la última hora disponible por estación, útil para la app y el rebalanceo.

Uso:
    python -m models.predict            # predice la última hora por estación
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common.config import get_settings
from common.db import get_connection
from common.logging_utils import get_logger

logger = get_logger(__name__)


def _load_artifact() -> tuple[object, dict]:
    art_dir = get_settings().path("models_artifacts")
    meta_path = art_dir / "model_meta.json"
    model_path = art_dir / "model.joblib"
    if not meta_path.exists() or not model_path.exists():
        raise FileNotFoundError(
            "No hay modelo entrenado. Ejecuta `python -m models.train` primero."
        )
    import joblib

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    model = joblib.load(model_path)
    return model, meta


def _prepare(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    if "station_code" in feature_cols and "station_code" not in df.columns:
        df["station_code"] = df["station_id"].astype("category").cat.codes
    X = df.reindex(columns=feature_cols)
    for c in X.columns:
        if X[c].dtype == bool:
            X[c] = X[c].astype(int)
    return X


def predict_frame(df: pd.DataFrame) -> np.ndarray:
    """Predice salidas para un DataFrame con las columnas de features."""
    model, meta = _load_artifact()
    X = _prepare(df, meta["feature_cols"])
    return np.clip(model.predict(X), 0, None)


def predict_latest() -> pd.DataFrame:
    """Predice la demanda de la última hora disponible por estación."""
    con = get_connection()
    feats = con.execute("SELECT * FROM model_features").df()
    con.close()
    if feats.empty:
        logger.warning("model_features vacío; entrena features y modelo.")
        return pd.DataFrame()
    latest_ts = feats["ts"].max()
    latest = feats[feats["ts"] == latest_ts].copy()
    latest["y_pred"] = predict_frame(latest)
    out = latest[["station_id", "ts", "y_pred"]].sort_values("y_pred", ascending=False)
    logger.info("Predicción para %s (%d estaciones)", latest_ts, len(out))
    return out


def main() -> int:
    out = predict_latest()
    if not out.empty:
        logger.info("Top demanda prevista:\n%s", out.head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
