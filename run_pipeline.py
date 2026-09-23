"""Orquestador del pipeline ECOBICI de punta a punta.

Modo muestra (por defecto): reconstruye la base con datos de muestra y ejecuta
todas las etapas analíticas. Reproduce el proyecto sin red ni descargas.

    python run_pipeline.py            # pipeline con datos de muestra
    python run_pipeline.py --full     # solo etapas analíticas sobre datos ya ingeridos

En modo --full se asume que ya se ejecutaron scrape/download/normalize y/o el
colector GBFS; este orquestador corre agregaciones, puente, features, modelo,
evaluación y rebalanceo sobre lo que exista en la base.
"""

from __future__ import annotations

import argparse

from common.config import get_settings
from common.logging_utils import get_logger

logger = get_logger(__name__)


def _reset_db() -> None:
    """Borra la base para una corrida de muestra limpia y determinista."""
    path = get_settings().duckdb_path
    for p in (path, path.with_suffix(path.suffix + ".wal")):
        if p.exists():
            p.unlink()
    logger.info("Base reiniciada: %s", path)


def run(sample: bool = True) -> None:
    from ingest.load_sample import load_sample
    from models.evaluate import evaluate
    from models.rebalance import build_recommendations
    from models.train import train
    from transform.build_aggregations import run as aggregate
    from transform.build_features import build as build_features
    from transform.build_station_bridge import build as build_bridge

    if sample:
        _reset_db()
        logger.info("== [1/7] Cargando datos de muestra ==")
        load_sample()
    else:
        logger.info("== Modo --full: usando datos ya ingeridos en la base ==")

    logger.info("== [2/7] Agregaciones por hora ==")
    aggregate()
    logger.info("== [3/7] Puente de estaciones ==")
    build_bridge()
    logger.info("== [4/7] Features ==")
    build_features()
    logger.info("== [5/7] Entrenamiento del modelo ==")
    train()
    logger.info("== [6/7] Evaluación ==")
    evaluate()
    logger.info("== [7/7] Rebalanceo ==")
    build_recommendations()
    logger.info("== Pipeline completo ==")


def main() -> int:
    parser = argparse.ArgumentParser(description="Orquestador del pipeline ECOBICI.")
    parser.add_argument("--full", action="store_true",
                        help="No usa muestra; corre etapas sobre datos ya ingeridos.")
    args = parser.parse_args()
    run(sample=not args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
