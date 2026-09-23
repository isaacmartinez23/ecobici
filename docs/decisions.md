# Decisiones de diseño (ADR ligero)

Registro cronológico de decisiones técnicas relevantes. Formato: contexto →
decisión → consecuencia.

## 2026-09-17 · Entorno y dependencias

- **Contexto**: entorno Windows 11, Python 3.14.3. Todas las dependencias
  (duckdb, pandas 3.0, scikit-learn, lightgbm 4.7, geopandas 1.1, streamlit,
  plotly, pydeck) instalan correctamente vía pip.
- **Decisión**: `pyproject.toml` fija `requires-python >=3.11`. LightGBM y
  GeoPandas se declaran como extras opcionales; el pipeline tiene alternativas
  (HistGradientBoosting de sklearn y haversine puro en `common/geo.py`).
- **Consecuencia**: el proyecto corre aunque falten los extras.

## 2026-09-17 · Paquete compartido `common/`

- **Decisión**: centralizar config (`settings.yaml` + overrides por env),
  logging, acceso DuckDB, tiempo y geo en un paquete `common/`. Los scripts se
  ejecutan como módulos (`python -m ingest.collect_gbfs`).
- **Consecuencia**: un único punto de verdad para rutas y umbrales; evita
  duplicación entre ingest/transform/models/app.

## 2026-09-17 · Timestamps

- **Decisión**: almacenar en DuckDB los timestamps como `TIMESTAMP` naive,
  entendidos por el nombre de la columna (`_utc` en UTC, `_local` en
  America/Mexico_City). El histórico se maneja en hora local (así vienen los
  CSV de ECOBICI).
- **Consecuencia**: comportamiento determinista, sin sorpresas de zona en
  DuckDB; se documenta el convenio.

## 2026-09-17 · Deduplicado del colector GBFS

- **Contexto**: GBFS es una foto del momento; corremos cada 5 min.
- **Decisión**: la llave de deduplicado de `station_status` es
  `(station_id, last_reported)`. Si `last_reported` es NULL, se inserta (no se
  puede deduplicar de forma segura). `station_information` solo se inserta si
  cambia nombre/lat/lon/capacidad.
- **Consecuencia**: correr el colector dos veces seguidas no duplica capturas
  (verificado con datos reales: 677 estaciones, 2ª corrida inserta 0).

## 2026-09-17 · Esquema DuckDB

- **Decisión**: `common/schema.sql` idempotente (CREATE TABLE IF NOT EXISTS).
  Las tablas derivadas (demand_hourly, availability_hourly, model_features,
  model_predictions, rebalance_recommendations) se reconstruyen con
  CREATE OR REPLACE en sus scripts, pero se declaran en el esquema para
  documentar grano y llaves.
- **Consecuencia**: `python -m transform...` puede correr repetidamente sin
  romper el estado.

## 2026-09-17 · Formatos de fecha del histórico

- **Contexto**: los CSV reales usan `%Y-%m-%d` (2010) y `%d/%m/%Y` (2025-2026);
  las horas traen o no microsegundos; la edad viene como `41.0` en años recientes.
- **Decisión**: parser que prueba formatos explícitos en orden. Se EXCLUYE
  `%m/%d/%Y` para no arriesgar el intercambio silencioso día/mes. La edad se
  coacciona con `to_numeric` y redondeo.
- **Consecuencia**: `31/12/2024` y `05/06/2025` se interpretan sin ambigüedad
  (verificado con prueba dedicada).

## 2026-09-17 · Esquema variable entre años

- **Contexto**: la columna de arribo aparece como `Ciclo_Estacion_Arribo` (2010)
  y `Ciclo_EstacionArribo` (2025). La snake_case ingenua no las unifica.
- **Decisión**: `to_snake_case` inserta guiones en límites camelCase y se apoya
  en un mapa de sinónimos, unificando ambas variantes a `ciclo_estacion_arribo`.

## 2026-09-17 · Demanda = demanda atendida

- **Decisión**: `demand_hourly.salidas` se declara explícitamente como demanda
  ATENDIDA (viajes observados). Los intentos frustrados con estación vacía no se
  observan y no se imputan.

## 2026-09-17 · Sin fuga temporal en features

- **Decisión**: todo rezago/ventana móvil aplica `shift(1)` por estación antes de
  la ventana, de modo que la hora t nunca entra en sus propias features. Se
  prueba con una serie lineal (roll_mean_3 en t = media de t-3..t-1).

## 2026-09-17 · Partición temporal (no aleatoria)

- **Decisión**: la evaluación usa fronteras por cuantiles del timestamp
  (train < val < test), nunca `train_test_split` aleatorio. Las fechas se derivan
  de los datos.

## 2026-09-17 · Rebalanceo heurístico

- **Decisión**: algoritmo greedy explicable, separado del modelo. Donantes solo
  ceden el excedente por encima del nivel objetivo (garantiza que no bajen de
  seguridad). Emparejamiento por cercanía con tope de distancia y de bicis por
  movimiento. La recomendación se etiqueta como ESTIMACIÓN.
- **Consecuencia**: invariantes verificadas por pruebas (capacidad, conservación
  de inventario, no-negatividad, sin donantes).

## 2026-09-17 · Datos de muestra sintéticos

- **Decisión**: generador determinista (semilla 42) que produce viajes en formato
  ECOBICI real + estaciones + serie de disponibilidad. Incluye filas inválidas a
  propósito. Permite `make all` sin red. Se versionan por ser pequeños (~2 MB).
- **Consecuencia**: las métricas mostradas por defecto provienen de datos
  SINTÉTICOS y no son conclusiones sobre ECOBICI real.
