# Diccionario de datos

Motor: DuckDB (`data/ecobici.duckdb`). Convenio de tiempo: columnas `_utc` en UTC
y `_local` en `America/Mexico_City`, almacenadas como `TIMESTAMP` naive. El
histórico se maneja en hora local (como vienen los CSV de ECOBICI).

Definición ejecutable del esquema: [`common/schema.sql`](../common/schema.sql).

---

## `ingestion_runs`
Trazabilidad de ejecuciones. **Grano**: una corrida. **Llave**: `run_id`.

| Columna | Tipo | Descripción |
|---|---|---|
| run_id | VARCHAR | Identificador único de la corrida |
| run_type | VARCHAR | `gbfs` \| `historical_download` \| `normalize` \| … |
| source | VARCHAR | URL o descripción de la fuente |
| started_at_utc / finished_at_utc | TIMESTAMP | Inicio/fin |
| status | VARCHAR | `running` \| `ok` \| `error` |
| rows_ingested | BIGINT | Filas ingeridas |
| notes | VARCHAR | Notas / JSON de calidad |

## `historical_file_manifest`
Manifiesto de archivos históricos. **Grano**: un archivo. **Llave**: `url`.

| Columna | Tipo | Descripción | Reglas de calidad |
|---|---|---|---|
| url | VARCHAR | URL real de descarga | única |
| file_name | VARCHAR | Nombre del archivo | |
| year, month | INTEGER | Periodo del DATO (no de la carpeta) | pueden ser NULL |
| discovered_at_utc | TIMESTAMP | Primer descubrimiento | |
| download_status | VARCHAR | `pending`\|`downloaded`\|`failed`\|`skipped` | |
| http_status | INTEGER | Código HTTP | |
| size_bytes | BIGINT | Tamaño | ≥ 0 |
| checksum_sha256 | VARCHAR | Checksum del archivo | evita re-descargas |
| local_path | VARCHAR | Ruta local | |
| last_downloaded_at_utc | TIMESTAMP | Última descarga | |

## `trips_raw`
Viajes crudos (staging), columnas en snake_case sin tipar. **Grano**: un viaje
crudo. **Fuente**: CSV históricos. Todas las columnas de datos son `VARCHAR` para
tolerar diferencias de esquema entre años.

`row_hash, source_file, run_id, ingested_at_utc, genero_usuario, edad_usuario,
bici, ciclo_estacion_retiro, fecha_retiro, hora_retiro, ciclo_estacion_arribo,
fecha_arribo, hora_arribo`.

## `trips_clean`
Viajes válidos y tipados. **Grano**: un viaje válido. **Llave**: `trip_id`.

| Columna | Tipo | Reglas |
|---|---|---|
| trip_id | VARCHAR | única |
| bike_id | VARCHAR | |
| origin_station_id / dest_station_id | VARCHAR | no nulos |
| retiro_ts / arribo_ts | TIMESTAMP | válidos; arribo > retiro |
| duration_min | DOUBLE | 1 ≤ x ≤ 240 |
| genero | VARCHAR | |
| edad | INTEGER | nullable |
| source_file, run_id | VARCHAR | trazabilidad |

## `trip_rejections`
Rechazos clasificados (no se borran). **Grano**: un viaje rechazado.

| Columna | Tipo | Descripción |
|---|---|---|
| row_hash | VARCHAR | Referencia a la fila cruda |
| source_file, run_id | VARCHAR | Origen |
| reason | VARCHAR | `duplicado`, `fecha_hora_invalida`, `estacion_origen_ausente`, `estacion_destino_ausente`, `arribo_no_posterior`, `duracion_muy_corta`, `duracion_muy_larga`, `bici_ausente` |
| detail | VARCHAR | Detalle opcional |
| retiro_raw / arribo_raw | VARCHAR | Valores crudos |
| rejected_at_utc | TIMESTAMP | Momento del rechazo |

## `station_information`
Catálogo GBFS por captura. **Grano**: estación × captura.

`station_id, name, lat, lon, capacity, region_id, short_name, captured_at_utc, run_id`.

## `station_status`
Serie temporal de disponibilidad GBFS. **Grano**: estación × captura (5 min).
**Dedupe**: `(station_id, last_reported)`.

| Columna | Tipo | Reglas |
|---|---|---|
| capture_id | VARCHAR | `station_id\|last_reported` |
| station_id | VARCHAR | no nulo |
| num_bikes_available / num_docks_available | INTEGER | ≥ 0 (negativos anulados) |
| is_installed / is_renting / is_returning | BOOLEAN | |
| last_reported | BIGINT | epoch UTC |
| captured_at_utc / captured_at_local | TIMESTAMP | |
| ingested_at_utc, run_id | | trazabilidad |

## `station_bridge`
Puente histórico↔GBFS. **Grano**: estación histórica. **Llave**: `historico_id`.

| Columna | Tipo | Descripción |
|---|---|---|
| historico_id / gbfs_id | VARCHAR | IDs emparejados |
| nombre_historico / nombre_gbfs | VARCHAR | Nombres |
| lat, lon | DOUBLE | Coordenadas GBFS |
| match_method | VARCHAR | `exact_id`\|`norm_name`\|`fuzzy_name`\|`geo`\|`manual_alias`\|`unmatched` |
| confidence | DOUBLE | 0..1 |
| distance_m | DOUBLE | Distancia (método geo) |
| manual_review | BOOLEAN | Requiere revisión |

## `demand_hourly`
Demanda por estación y hora. **Grano**: estación × fecha × hora.

`station_id, date, hour, dow (0=lunes), salidas, llegadas, flujo_neto (=llegadas-salidas),
demanda_atendida (=salidas)`.

## `availability_hourly`
Disponibilidad por estación y hora. **Grano**: estación × fecha × hora.

`station_id, date, hour, bikes_start, bikes_end, bikes_min, bikes_max,
minutes_zero_bikes, minutes_zero_docks, empty_flag, full_flag, n_captures`.

## `model_features`
Variables predictivas. **Grano**: estación × hora. Objetivo: `salidas`. Incluye
calendario (hour, dow, is_weekend, month, week, is_holiday, quincena), metadatos
(capacity, lat, lon), disponibilidad rezagada (`bikes_end_lag_1`), rezagos
(`salidas_lag_{1,2,24,168}`) y ventanas móviles (`salidas_roll_{mean,median}_{3,24,168}`).
**Todas las variables temporales usan solo información anterior a la hora predicha.**

## `model_predictions`
Predicciones. **Grano**: estación × hora × objetivo.

`station_id, ts, target, y_true, y_pred_baseline, y_pred_model, split (train|val|test),
model_version, created_at_utc`.

## `rebalance_recommendations`
Movimientos recomendados. **Grano**: un movimiento donante→receptora por ventana.

`target_ts, donor_station_id, receiver_station_id, bikes_to_move, distance_m,
donor_inventory_before/after, receiver_inventory_before/after,
receiver_deficit_before/after, confidence, model_version, created_at_utc`.
