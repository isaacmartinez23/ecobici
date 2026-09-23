-- Esquema analítico de ECOBICI en DuckDB.
-- Idempotente: usa CREATE TABLE IF NOT EXISTS. Los timestamps _utc/_local se
-- almacenan como TIMESTAMP naive entendidos en su zona indicada por el nombre.
-- Las tablas derivadas por el pipeline (demand_hourly, model_features, etc.) se
-- reconstruyen con CREATE OR REPLACE en sus scripts; aquí se definen para
-- documentar el grano y permitir consultas aunque estén vacías.

-- ============================================================
-- Trazabilidad de ejecuciones
-- Grano: una fila por corrida de un componente de ingestión/transformación.
-- Llave: run_id.
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id            VARCHAR PRIMARY KEY,
    run_type          VARCHAR NOT NULL,      -- 'gbfs' | 'historical_download' | 'normalize' | ...
    source            VARCHAR,               -- URL o descripción de la fuente
    started_at_utc    TIMESTAMP NOT NULL,
    finished_at_utc   TIMESTAMP,
    status            VARCHAR NOT NULL,       -- 'running' | 'ok' | 'error'
    rows_ingested     BIGINT DEFAULT 0,
    notes             VARCHAR
);

-- ============================================================
-- Manifiesto de archivos históricos descubiertos/descargados
-- Grano: una fila por URL de archivo histórico.
-- Llave: url.
-- ============================================================
CREATE TABLE IF NOT EXISTS historical_file_manifest (
    url                  VARCHAR PRIMARY KEY,
    file_name            VARCHAR,
    year                 INTEGER,            -- puede ser NULL si no se infiere
    month                INTEGER,            -- puede ser NULL si no se infiere
    discovered_at_utc    TIMESTAMP NOT NULL,
    download_status      VARCHAR DEFAULT 'pending',  -- pending|downloaded|failed|skipped
    http_status          INTEGER,
    size_bytes           BIGINT,
    checksum_sha256      VARCHAR,
    local_path           VARCHAR,
    last_downloaded_at_utc TIMESTAMP
);

-- ============================================================
-- Viajes crudos (staging). Columnas en snake_case pero SIN tipar (VARCHAR)
-- para tolerar diferencias de esquema entre años.
-- Grano: una fila por viaje crudo. Llave lógica: row_hash + source_file.
-- ============================================================
CREATE TABLE IF NOT EXISTS trips_raw (
    row_hash              VARCHAR,
    source_file           VARCHAR,
    run_id                VARCHAR,
    ingested_at_utc       TIMESTAMP,
    genero_usuario        VARCHAR,
    edad_usuario          VARCHAR,
    bici                  VARCHAR,
    ciclo_estacion_retiro VARCHAR,
    fecha_retiro          VARCHAR,
    hora_retiro           VARCHAR,
    ciclo_estacion_arribo VARCHAR,
    fecha_arribo          VARCHAR,
    hora_arribo           VARCHAR
);

-- ============================================================
-- Viajes limpios y tipados.
-- Grano: una fila por viaje válido. Llave lógica: trip_id.
-- ============================================================
CREATE TABLE IF NOT EXISTS trips_clean (
    trip_id            VARCHAR PRIMARY KEY,
    bike_id            VARCHAR,
    origin_station_id  VARCHAR,
    dest_station_id    VARCHAR,
    retiro_ts          TIMESTAMP NOT NULL,   -- hora local America/Mexico_City
    arribo_ts          TIMESTAMP NOT NULL,
    duration_min       DOUBLE,
    genero             VARCHAR,
    edad               INTEGER,
    source_file        VARCHAR,
    run_id             VARCHAR
);

-- ============================================================
-- Rechazos del histórico, clasificados por causa (no se borran).
-- Grano: una fila por viaje rechazado. Llave lógica: row_hash + reason.
-- ============================================================
CREATE TABLE IF NOT EXISTS trip_rejections (
    row_hash        VARCHAR,
    source_file     VARCHAR,
    run_id          VARCHAR,
    reason          VARCHAR NOT NULL,   -- ver models/constantes de motivos
    detail          VARCHAR,
    retiro_raw      VARCHAR,
    arribo_raw      VARCHAR,
    rejected_at_utc TIMESTAMP
);

-- ============================================================
-- Información de estaciones (GBFS station_information).
-- Grano: una fila por estación por captura. Llave lógica: station_id + captured_at_utc.
-- ============================================================
CREATE TABLE IF NOT EXISTS station_information (
    station_id      VARCHAR,
    name            VARCHAR,
    lat             DOUBLE,
    lon             DOUBLE,
    capacity        INTEGER,
    region_id       VARCHAR,
    short_name      VARCHAR,
    captured_at_utc TIMESTAMP,
    run_id          VARCHAR
);

-- ============================================================
-- Estado de estaciones (GBFS station_status), serie temporal.
-- Grano: una fila por estación por captura de 5 min.
-- Llave lógica: station_id + last_reported + captured_at_utc (dedupe).
-- ============================================================
CREATE TABLE IF NOT EXISTS station_status (
    capture_id           VARCHAR,
    station_id           VARCHAR NOT NULL,
    num_bikes_available  INTEGER,
    num_docks_available  INTEGER,
    is_installed         BOOLEAN,
    is_renting           BOOLEAN,
    is_returning         BOOLEAN,
    last_reported        BIGINT,          -- epoch UTC segundos
    captured_at_utc      TIMESTAMP NOT NULL,
    captured_at_local    TIMESTAMP,
    ingested_at_utc      TIMESTAMP,
    run_id               VARCHAR
);

-- ============================================================
-- Puente de estaciones histórico <-> GBFS.
-- Grano: una fila por estación histórica emparejada. Llave: historico_id.
-- ============================================================
CREATE TABLE IF NOT EXISTS station_bridge (
    historico_id      VARCHAR PRIMARY KEY,
    gbfs_id           VARCHAR,
    nombre_historico  VARCHAR,
    nombre_gbfs       VARCHAR,
    lat               DOUBLE,
    lon               DOUBLE,
    match_method      VARCHAR,   -- exact_id|norm_name|fuzzy_name|geo|manual_alias|unmatched
    confidence        DOUBLE,    -- 0..1
    distance_m        DOUBLE,
    manual_review     BOOLEAN DEFAULT FALSE
);

-- ============================================================
-- Demanda por estación y hora (derivada de trips_clean).
-- Grano: estación x fecha x hora. Llave lógica: station_id + date + hour.
-- ============================================================
CREATE TABLE IF NOT EXISTS demand_hourly (
    station_id       VARCHAR,
    date             DATE,
    hour             INTEGER,
    dow              INTEGER,        -- 0=lunes .. 6=domingo
    salidas          INTEGER,        -- demanda atendida de retiro
    llegadas         INTEGER,
    flujo_neto       INTEGER,        -- llegadas - salidas
    demanda_atendida INTEGER         -- = salidas (viajes observados)
);

-- ============================================================
-- Disponibilidad por estación y hora (derivada de station_status).
-- Grano: estación x fecha x hora. Llave lógica: station_id + date + hour.
-- ============================================================
CREATE TABLE IF NOT EXISTS availability_hourly (
    station_id          VARCHAR,
    date                DATE,
    hour                INTEGER,
    bikes_start         INTEGER,
    bikes_end           INTEGER,
    bikes_min           INTEGER,
    bikes_max           INTEGER,
    minutes_zero_bikes  DOUBLE,
    minutes_zero_docks  DOUBLE,
    empty_flag          BOOLEAN,
    full_flag           BOOLEAN,
    n_captures          INTEGER
);

-- ============================================================
-- Tabla de features del modelo (se reconstruye con CREATE OR REPLACE).
-- Grano: estación x hora. Definición representativa con los lags por defecto.
-- ============================================================
CREATE TABLE IF NOT EXISTS model_features (
    station_id    VARCHAR,
    ts            TIMESTAMP,       -- inicio de la hora, local
    hour          INTEGER,
    dow           INTEGER,
    is_weekend    BOOLEAN,
    month         INTEGER,
    week          INTEGER,
    is_holiday    BOOLEAN,
    quincena      BOOLEAN,
    capacity      INTEGER,
    lat           DOUBLE,
    lon           DOUBLE,
    salidas       DOUBLE,          -- objetivo
    llegadas      DOUBLE,
    flujo_neto    DOUBLE,
    salidas_lag_1     DOUBLE,
    salidas_lag_2     DOUBLE,
    salidas_lag_24    DOUBLE,
    salidas_lag_168   DOUBLE,
    salidas_roll_mean_3    DOUBLE,
    salidas_roll_median_3  DOUBLE,
    salidas_roll_mean_24   DOUBLE,
    salidas_roll_median_24 DOUBLE,
    salidas_roll_mean_168  DOUBLE,
    salidas_roll_median_168 DOUBLE
);

-- ============================================================
-- Predicciones del modelo y línea base.
-- Grano: estación x hora x objetivo. Llave lógica: station_id + ts + target.
-- ============================================================
CREATE TABLE IF NOT EXISTS model_predictions (
    station_id      VARCHAR,
    ts              TIMESTAMP,
    target          VARCHAR,
    y_true          DOUBLE,
    y_pred_baseline DOUBLE,
    y_pred_model    DOUBLE,
    split           VARCHAR,       -- train|val|test
    model_version   VARCHAR,
    created_at_utc  TIMESTAMP
);

-- ============================================================
-- Recomendaciones de rebalanceo.
-- Grano: un movimiento donante->receptora por ventana objetivo.
-- ============================================================
CREATE TABLE IF NOT EXISTS rebalance_recommendations (
    target_ts                  TIMESTAMP,
    donor_station_id           VARCHAR,
    receiver_station_id        VARCHAR,
    bikes_to_move              INTEGER,
    distance_m                 DOUBLE,
    donor_inventory_before     DOUBLE,
    donor_inventory_after      DOUBLE,
    receiver_inventory_before  DOUBLE,
    receiver_inventory_after   DOUBLE,
    receiver_deficit_before    DOUBLE,
    receiver_deficit_after     DOUBLE,
    confidence                 DOUBLE,
    model_version              VARCHAR,
    created_at_utc             TIMESTAMP
);
