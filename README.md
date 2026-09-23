# ECOBICI: dónde faltan bicicletas y a qué hora

Sistema reproducible para responder, con datos abiertos de ECOBICI (CDMX) y el
feed GBFS en tiempo real:

- ¿Qué estaciones tienen mayor riesgo de quedarse sin bicicletas y en qué franjas?
- ¿Qué estaciones acumulan bicicletas y pueden donarlas?
- ¿Cuántas bicicletas mover, desde dónde y hacia dónde?
- ¿Qué porcentaje del desabasto estimado podría evitarse con el rebalanceo?

Combina histórico de viajes, disponibilidad GBFS, una línea base estadística, un
modelo de demanda, un algoritmo de rebalanceo, una app Streamlit, pruebas y
documentación.

## Respuesta corta

> **Pendiente de datos reales.** La infraestructura está completa y validada de
> punta a punta con **datos de muestra sintéticos**. Para obtener conclusiones
> reales sobre ECOBICI, descarga el histórico y ejecuta el pipeline en modo
> `--full` (ver *Cómo reproducir*). Las cifras que muestra la app por defecto
> provienen de datos sintéticos y **no** son afirmaciones sobre el sistema real.

## Arquitectura

Pipeline en capas con **DuckDB** como motor analítico local y **Streamlit** como
interfaz. Detalle en [`docs/architecture.md`](docs/architecture.md).

```
Fuentes → Ingestión → Transformación → Modelado → App
  Open-data (CSV)   scrape/download/normalize   demand_hourly
  GBFS (JSON)       collect_gbfs                availability_hourly
                    load_sample (muestra)       model_features → baseline/modelo
                                                station_bridge  → rebalanceo → Streamlit
```

## Fuentes y cobertura

| Fuente | URL | Uso |
|---|---|---|
| Histórico de viajes | https://ecobici.cdmx.gob.mx/en/open-data/ | Demanda por estación/hora |
| GBFS (discovery) | https://gbfs.mex.lyftbikes.com/gbfs/gbfs.json | Disponibilidad en tiempo real |

- El scraper descubre **198 archivos** históricos reales (2010–2026) y deduce
  año/mes del **nombre** (la carpeta de publicación no coincide con el mes).
- El feed GBFS real expone **~677 estaciones**. El colector guarda `station_status`
  cada 5 minutos de forma idempotente.

## Cómo reproducir

Requisitos: Python ≥ 3.11.

### Con Make (Linux/macOS)

```bash
make setup      # crea .venv e instala dependencias
make all        # pipeline completo con datos de MUESTRA
make app        # lanza Streamlit
make test       # pruebas
make lint       # ruff
```

### Sin Make (Windows u otros)

```bash
python -m venv .venv
.venv\Scripts\activate            # en Windows (Linux/mac: source .venv/bin/activate)
pip install -e ".[dev]"
pip install -r requirements-optional.txt   # LightGBM/GeoPandas (opcional)

python run_pipeline.py            # pipeline completo con datos de muestra
python -m pytest                  # pruebas
ruff check .                      # lint
streamlit run app/app.py          # app
```

### Con datos reales

```bash
python -m ingest.scrape_historical_urls          # manifiesto de URLs
python -m ingest.download_historical --latest 2  # descarga los 2 meses más recientes
python -m ingest.download_historical --from 2025-01 --to 2025-06   # o un rango
python -m transform.normalize_historical         # limpia -> trips_clean
python -m ingest.collect_gbfs                     # una captura de disponibilidad
python run_pipeline.py --full                     # agregaciones→modelo→rebalanceo
```

## Cómo activar el colector

- **Local**: `python -m ingest.collect_gbfs` (repetible; idempotente). Para una
  serie, prográmalo cada 5 min (cron/Task Scheduler).
- **CI**: `.github/workflows/collect_gbfs.yml` corre el colector cada 5 min
  (aproximado; los runners son efímeros) y sube cada captura como artefacto.
  Estrategias de persistencia durable (S3, base gestionada, rama de datos) están
  documentadas en el propio workflow. **No subas secretos**; usa GitHub Secrets.

## Cómo ejecutar Streamlit

```bash
streamlit run app/app.py
```
Secciones: Resumen ejecutivo, Mapa interactivo, Demanda por estación, Rebalanceo,
Calidad y limitaciones. Funciona con los datos de muestra cargados por el pipeline.

## Método

1. **Ingestión**: scraping de enlaces reales + descarga con checksum + colector
   GBFS idempotente.
2. **Normalización**: snake_case tolerante a variantes de esquema, parser de
   fechas con formatos explícitos, clasificación de rechazos.
3. **Puente de estaciones**: alias manual → id exacto → nombre → fuzzy → geografía.
4. **Agregaciones**: `demand_hourly` y `availability_hourly` por estación/hora.
5. **Features**: calendario, rezagos y ventanas móviles **sin fuga temporal**.
6. **Modelo**: línea base de medianas vs. LightGBM (respaldo sklearn), con
   **partición temporal** (no aleatoria).
7. **Rebalanceo**: heurística explicable donante→receptora.

## Reglas de limpieza

Un viaje se **rechaza** (y se conserva en `trip_rejections` con su causa) si:

| Motivo | Regla |
|---|---|
| `duplicado` | fila repetida (misma llave lógica) |
| `fecha_hora_invalida` | retiro o arribo no parseable |
| `estacion_origen_ausente` / `estacion_destino_ausente` | estación nula/vacía |
| `arribo_no_posterior` | arribo ≤ retiro |
| `duracion_muy_corta` | < 1 minuto |
| `duracion_muy_larga` | > 240 minutos |
| `bici_ausente` | identificador de bici ausente |

Se reportan totales, % rechazado y desglose por motivo/archivo en
`reports/rejection_report.csv`.

## Comparación línea base vs. modelo

La evaluación es **temporal** (train < val < test). Métricas: MAE, RMSE, WAPE,
sesgo; global y por estación/hora/horas pico/estaciones top. Salidas en
`reports/metrics_*.csv` y figuras en `reports/figures/`.

> **[muestra, sintético]** MAE en prueba: línea base ≈ **0.63**, modelo ≈ **0.61**
> salidas/hora (mejora ≈ **3.6 %**); RMSE ≈ 0.98 vs. 0.83. Con datos reales estas
> cifras cambiarán; si el modelo no supera a la base, se reporta tal cual.

## Hallazgos

`PENDIENTE (dato real)`. Con la muestra sintética (semilla 42, periodo
2025-06-01 → 2025-06-29), la app genera el ranking de riesgo y los perfiles
horarios; **no** constituyen hallazgos sobre ECOBICI real.

## Recomendación de rebalanceo

Tabla descargable en la sección **Rebalanceo** (donante, receptora, bicis a mover,
distancia, déficit antes/después, confianza). Es una **estimación**, no un hecho.
Garantías del algoritmo (verificadas por pruebas): respeta capacidad, conserva el
inventario, no mueve cantidades negativas y no deja a la donante bajo su nivel de
seguridad.

## Limitaciones

Ver [`docs/limitations.md`](docs/limitations.md).

## Estructura del repositorio

```
ecobici/
├── app/            # Streamlit (app.py, components/, utils/)
├── common/         # config, db+schema.sql, http, timeutils, geo, logging
├── config/         # settings.yaml, station_aliases.csv
├── data/           # raw/ interim/ processed/ manifests/ sample/ (crudos ignorados)
├── docs/           # architecture, data_dictionary, decisions, limitations, especificacion
├── ingest/         # scrape, download, collect_gbfs, load_raw/load_sample
├── models/         # baseline, train, evaluate, predict, rebalance, metrics
├── reports/        # métricas, figuras, memo.md
├── transform/      # normalize, bridge, *.sql, aggregations, features
├── tests/          # pytest (ingestión, normalización, calidad, features, bridge, rebalance)
├── run_pipeline.py # orquestador (muestra por defecto; --full para datos reales)
├── LICENSE  Makefile  pyproject.toml  requirements*.txt  .github/workflows/
```

## Diccionario de datos

Ver [`docs/data_dictionary.md`](docs/data_dictionary.md) y la definición ejecutable
en [`common/schema.sql`](common/schema.sql).

## Lo que este análisis NO puede decir

- Los **viajes representan demanda atendida**: los retiros que efectivamente
  ocurrieron.
- **No se observan directamente los intentos frustrados**: donde la estación se
  vacía, la demanda real está subestimada.
- La **cobertura GBFS comienza cuando se enciende el colector**; no hay historia
  previa.
- Una **predicción no garantiza disponibilidad futura**.
- El modelo **no incorpora** tráfico, clima, costo de traslado ni restricciones
  operativas completas, salvo que existan datos reales para ello.

## Licencia y atribución de datos

Este proyecto se distribuye bajo licencia **MIT** (ver [`LICENSE`](LICENSE)).

**Datos**: el repositorio **no** redistribuye datos de ECOBICI. Solo incluye los
*scripts* que los descargan y **datos de muestra sintéticos** generados localmente
(`data/sample/`). Las fuentes originales y sus términos pertenecen a sus
responsables:

- Histórico de viajes: [Datos abiertos de ECOBICI — Gobierno de la CDMX](https://ecobici.cdmx.gob.mx/en/open-data/).
- Disponibilidad en tiempo real: feed **GBFS** de ECOBICI (operado por Lyft),
  `https://gbfs.mex.lyftbikes.com/gbfs/gbfs.json`.

Al descargar y publicar datos derivados, respeta los términos de uso de cada
fuente. La especificación original del proyecto está en
[`docs/especificacion.md`](docs/especificacion.md).

## Próximos pasos

1. Descargar un rango real del histórico y correr `run_pipeline.py --full` para
   sustituir las cifras `PENDIENTE` por resultados reales.
2. Acumular ≥ 2 semanas de capturas GBFS para robustecer disponibilidad y
   rebalanceo (persistencia durable en S3/base gestionada).
3. Construir un catálogo histórico de estaciones (nombre + coordenadas) para
   activar el emparejamiento por nombre/geografía del puente en datos reales.
