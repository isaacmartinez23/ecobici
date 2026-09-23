# Arquitectura

## Visión general

Pipeline reproducible en capas, con DuckDB como motor analítico local y Streamlit
como interfaz. Todo el estado analítico vive en `data/ecobici.duckdb` (excluido de
Git); el código y la configuración lo reconstruyen.

```
Fuentes                Ingestión                 Transformación            Modelado            App
────────               ─────────                 ──────────────            ────────            ───
Open-data (CSV)  ──▶  scrape_historical_urls ─┐
                      download_historical    ─┼─▶ normalize_historical ─▶ trips_clean ─┐
GBFS (JSON)      ──▶  collect_gbfs           ─┘   build_station_bridge     station_*    │
                      load_sample (muestra)        build_aggregations ─▶ demand_hourly  │
                                                    build_features    ─▶ availability_h ─┼─▶ baseline
                                                                          model_features │   train ─▶ model_predictions
                                                                                         │   evaluate ─▶ reports/
                                                                                         └─▶ rebalance ─▶ rebalance_recommendations
                                                                                                              │
                                                                                                              ▼
                                                                                                         Streamlit
```

## Capas

1. **Ingestión** (`ingest/`)
   - `scrape_historical_urls.py`: descubre enlaces reales del portal open-data y
     escribe `data/manifests/ecobici_historico.csv`. Deduce año/mes del nombre.
   - `download_historical.py`: descarga por rango de meses, con checksum SHA-256,
     manejo de ZIP/CSV y reintentos; evita re-descargas sin cambios.
   - `collect_gbfs.py`: captura `station_status`/`station_information` cada 5 min,
     idempotente por `(station_id, last_reported)`.
   - `load_sample.py`: carga datos de muestra sintéticos para correr sin red.

2. **Transformación** (`transform/`)
   - `normalize_historical.py`: snake_case, parser de fechas explícito,
     clasificación de rechazos → `trips_clean`, `trip_rejections`, `trips_raw`.
   - `build_station_bridge.py`: puente histórico↔GBFS (id/nombre/fuzzy/geo/alias).
   - `*.sql` + `build_aggregations.py`: `demand_hourly`, `availability_hourly`.
   - `build_features.py`: variables de calendario, rezagos y ventanas móviles sin
     fuga temporal → `model_features`.

3. **Modelado** (`models/`)
   - `baseline.py`: medianas jerárquicas (estación×dow×hora → estación×hora → hora).
   - `train.py`: partición temporal + LightGBM (respaldo sklearn) → `model_predictions`.
   - `evaluate.py`: MAE/RMSE/WAPE/sesgo por segmento; figuras y CSV.
   - `rebalance.py`: heurística donante→receptora → `rebalance_recommendations`.

4. **Aplicación** (`app/`)
   - `app.py` + `components/sections.py` + `utils/data.py`: 5 secciones en español.

## Configuración y utilidades compartidas (`common/`)

- `config.py`: carga `config/settings.yaml` con overrides por variables de entorno.
- `db.py` + `schema.sql`: conexión y creación idempotente del esquema.
- `http.py`: cliente con reintentos/backoff/timeout.
- `timeutils.py`: zona horaria `America/Mexico_City`.
- `geo.py`: haversine puro (sin depender de GeoPandas).
- `logging_utils.py`: logging estructurado.

## Reproducibilidad

- `run_pipeline.py` orquesta todo con datos de muestra (`--full` para datos reales
  ya ingeridos).
- El `Makefile` expone objetivos por etapa; en Windows se usan los `python -m …`
  equivalentes.
- CI (`.github/workflows/ci.yml`) corre lint, pruebas, el pipeline de muestra y la
  verificación de arranque de Streamlit.
