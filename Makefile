# Makefile de ECOBICI. En Windows (sin make) usa los equivalentes `python -m ...`
# documentados en el README. Objetivos principales: `make setup` y `make all`.

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
PY := $(BIN)/python
PIP := $(BIN)/pip

.PHONY: help setup sample scrape download collect-gbfs ingest transform \
        features train evaluate recommend app test lint all clean

help:
	@echo "Objetivos disponibles:"
	@echo "  setup        Crea el entorno virtual e instala dependencias"
	@echo "  sample       Genera y carga datos de muestra en DuckDB"
	@echo "  scrape       Descubre URLs del histórico (manifiesto)"
	@echo "  download     Descarga histórico (usa FROM/TO/LATEST, p.ej. LATEST=1)"
	@echo "  collect-gbfs Captura una foto GBFS de disponibilidad"
	@echo "  ingest       Carga datos de muestra (alias de sample)"
	@echo "  transform    Agregaciones por hora + puente de estaciones"
	@echo "  features     Construye variables predictivas"
	@echo "  train        Entrena línea base + modelo"
	@echo "  evaluate     Evalúa (temporal) y genera figuras"
	@echo "  recommend    Genera recomendaciones de rebalanceo"
	@echo "  app          Lanza la app Streamlit"
	@echo "  test         Ejecuta pytest"
	@echo "  lint         Ejecuta ruff"
	@echo "  all          Pipeline completo con datos de muestra"
	@echo "  clean        Borra artefactos regenerables"

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	-$(PIP) install -r requirements-optional.txt
	@echo "Entorno listo. Activa con: source $(BIN)/activate"

sample:
	$(PY) data/sample/generate_sample.py
	$(PY) -m ingest.load_sample

ingest: sample

scrape:
	$(PY) -m ingest.scrape_historical_urls

# Uso: make download LATEST=1  |  make download FROM=2025-06 TO=2025-08
LATEST ?=
FROM ?=
TO ?=
download:
	$(PY) -m ingest.download_historical $(if $(LATEST),--latest $(LATEST),) \
		$(if $(FROM),--from $(FROM),) $(if $(TO),--to $(TO),)

collect-gbfs:
	$(PY) -m ingest.collect_gbfs

transform:
	$(PY) -m transform.build_aggregations
	$(PY) -m transform.build_station_bridge

features:
	$(PY) -m transform.build_features

train:
	$(PY) -m models.train

evaluate:
	$(PY) -m models.evaluate

recommend:
	$(PY) -m models.rebalance

app:
	$(BIN)/streamlit run app/app.py

test:
	$(PY) -m pytest

lint:
	$(BIN)/ruff check .

all:
	$(PY) run_pipeline.py

clean:
	rm -f data/ecobici.duckdb data/ecobici.duckdb.wal
	rm -rf models/artifacts data/processed/*.parquet reports/figures/*.png
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Limpieza completa."
