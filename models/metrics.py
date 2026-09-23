"""Métricas de evaluación de pronóstico."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Weighted Absolute Percentage Error. NaN si el denominador es 0."""
    denom = np.sum(np.abs(y_true))
    if denom == 0:
        return float("nan")
    return float(np.sum(np.abs(y_true - y_pred)) / denom)


def mean_bias(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Sesgo medio: positivo => sobreestima."""
    return float(np.mean(y_pred - y_true))


def compute_all(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "wape": wape(y_true, y_pred),
        "sesgo_medio": mean_bias(y_true, y_pred),
        "n": int(len(y_true)),
    }


def metrics_by_group(df: pd.DataFrame, y_true_col: str, y_pred_col: str,
                     group_col: str) -> pd.DataFrame:
    """Métricas por grupo (estación u hora)."""
    out = []
    for key, g in df.groupby(group_col):
        m = compute_all(g[y_true_col].to_numpy(), g[y_pred_col].to_numpy())
        m[group_col] = key
        out.append(m)
    return pd.DataFrame(out).sort_values(group_col).reset_index(drop=True)
