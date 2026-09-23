-- Disponibilidad por estación y hora, derivada de station_status.
-- Grano: estación x fecha x hora (local). Fuente: station_status.
-- Los minutos con cero bicis/anclajes asumen capturas cada 5 minutos.
CREATE OR REPLACE TABLE availability_hourly AS
WITH base AS (
    SELECT
        station_id,
        CAST(captured_at_local AS DATE) AS date,
        CAST(EXTRACT(hour FROM captured_at_local) AS INTEGER) AS hour,
        captured_at_local,
        num_bikes_available AS bikes,
        num_docks_available AS docks
    FROM station_status
    WHERE captured_at_local IS NOT NULL
)
SELECT
    station_id,
    date,
    hour,
    arg_min(bikes, captured_at_local) AS bikes_start,
    arg_max(bikes, captured_at_local) AS bikes_end,
    min(bikes) AS bikes_min,
    max(bikes) AS bikes_max,
    5.0 * SUM(CASE WHEN bikes = 0 THEN 1 ELSE 0 END) AS minutes_zero_bikes,
    5.0 * SUM(CASE WHEN docks = 0 THEN 1 ELSE 0 END) AS minutes_zero_docks,
    bool_or(bikes = 0) AS empty_flag,
    bool_or(docks = 0) AS full_flag,
    COUNT(*) AS n_captures
FROM base
GROUP BY station_id, date, hour
ORDER BY station_id, date, hour;
