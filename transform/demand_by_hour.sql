-- Demanda por estación y hora, derivada de trips_clean.
-- Grano: estación x fecha x hora. Fuente: trips_clean.
-- Nota: 'salidas' = demanda ATENDIDA de retiro (viajes observados). Cuando una
-- estación está vacía, los intentos frustrados NO aparecen aquí.
-- dow: 0 = lunes ... 6 = domingo.
CREATE OR REPLACE TABLE demand_hourly AS
WITH salidas AS (
    SELECT
        origin_station_id AS station_id,
        CAST(retiro_ts AS DATE) AS date,
        CAST(EXTRACT(hour FROM retiro_ts) AS INTEGER) AS hour,
        COUNT(*) AS salidas
    FROM trips_clean
    GROUP BY 1, 2, 3
),
llegadas AS (
    SELECT
        dest_station_id AS station_id,
        CAST(arribo_ts AS DATE) AS date,
        CAST(EXTRACT(hour FROM arribo_ts) AS INTEGER) AS hour,
        COUNT(*) AS llegadas
    FROM trips_clean
    GROUP BY 1, 2, 3
),
grid AS (
    SELECT station_id, date, hour FROM salidas
    UNION
    SELECT station_id, date, hour FROM llegadas
)
SELECT
    g.station_id,
    g.date,
    g.hour,
    CAST((CAST(EXTRACT(dow FROM g.date) AS INTEGER) + 6) % 7 AS INTEGER) AS dow,
    COALESCE(s.salidas, 0) AS salidas,
    COALESCE(l.llegadas, 0) AS llegadas,
    COALESCE(l.llegadas, 0) - COALESCE(s.salidas, 0) AS flujo_neto,
    COALESCE(s.salidas, 0) AS demanda_atendida
FROM grid g
LEFT JOIN salidas s USING (station_id, date, hour)
LEFT JOIN llegadas l USING (station_id, date, hour)
ORDER BY g.station_id, g.date, g.hour;
