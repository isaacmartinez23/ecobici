# Análisis

Espacio para exploración (notebooks o scripts) apoyada en las tablas de DuckDB.
El pipeline deja listas las tablas analíticas; aquí se documentan hallazgos.

## Cómo empezar

```python
import duckdb
con = duckdb.connect("data/ecobici.duckdb", read_only=True)

# Demanda por hora del día (todas las estaciones)
con.execute("""
    SELECT hour, AVG(salidas) AS salidas_prom
    FROM demand_hourly GROUP BY hour ORDER BY hour
""").df()

# Estaciones con más minutos sin bicis
con.execute("""
    SELECT station_id, SUM(minutes_zero_bikes) AS min_sin_bicis
    FROM availability_hourly GROUP BY 1 ORDER BY 2 DESC LIMIT 10
""").df()
```

## Insumos disponibles

- `reports/metrics_*.csv`: métricas de evaluación por segmento.
- `reports/rejection_report.csv`: rechazos por archivo y motivo.
- `reports/figures/*.png`: figuras de comparación línea base vs. modelo.
- `data/processed/model_features.parquet`: features listas para modelar.

> Nota: por defecto las tablas contienen datos de **muestra** sintéticos. Para
> análisis reales, carga el histórico y corre `python run_pipeline.py --full`.
