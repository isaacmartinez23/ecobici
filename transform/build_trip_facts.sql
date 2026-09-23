-- Vista de hechos de viaje: trips_clean enriquecida con la hora truncada de
-- retiro y arribo. Grano: un viaje válido. Fuente: trips_clean.
CREATE OR REPLACE VIEW trip_facts AS
SELECT
    trip_id,
    bike_id,
    origin_station_id,
    dest_station_id,
    retiro_ts,
    arribo_ts,
    duration_min,
    date_trunc('hour', retiro_ts) AS retiro_hour,
    date_trunc('hour', arribo_ts) AS arribo_hour
FROM trips_clean;
