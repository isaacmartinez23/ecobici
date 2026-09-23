# Memo ejecutivo — ECOBICI: dónde faltan bicicletas y a qué hora

**Para**: persona que decide presupuesto de operación.
**De**: equipo de datos.
**Estado**: infraestructura completa y validada. Los números cuantitativos de
abajo requieren correr el pipeline sobre el **histórico real** descargado; hasta
entonces se marcan como `PENDIENTE (dato real)`. Los valores entre corchetes con
la etiqueta `[muestra]` provienen de datos **sintéticos** y son solo ilustrativos.

---

## 1. Qué preguntamos

¿Qué estaciones se quedan sin bicicletas, en qué días y horas, y cuántas bicis
convendría mover —y desde dónde— para reducir el desabasto?

## 2. Qué encontramos

- Estaciones con mayor riesgo de vaciado: `PENDIENTE (dato real)`
  — _[muestra]: el ranking se genera en el Resumen ejecutivo de la app._
- Franjas críticas (día/hora): `PENDIENTE (dato real)`
  — _[muestra]: patrón entre semana con picos de commute ~8–9 h y ~18–19 h._
- Comparación línea base vs. modelo (MAE en prueba): `PENDIENTE (dato real)`
  — _[muestra]: MAE base ≈ 0.63 vs. modelo ≈ 0.61 salidas/hora (mejora ~3.6 %)._

> Los viajes miden **demanda atendida**: donde la estación se vacía, la demanda
> real está subestimada (ver limitaciones).

## 3. Qué recomendamos hacer

- Priorizar el reabasto de las estaciones receptoras identificadas en las franjas
  críticas, tomando bicis de las donantes cercanas por encima de su nivel objetivo.
- Movimientos concretos (donante→receptora, bicis, distancia): ver la tabla
  descargable de la sección **Rebalanceo** de la app.
  — _[muestra]: 3 movimientos, 7 bicis, déficit estimado 1→0._

## 4. Qué impacto estimamos

- Porcentaje de desabasto estimado evitable con el rebalanceo propuesto:
  `PENDIENTE (dato real)` — _[muestra]: ~100 % del déficit de la franja objetivo,
  bajo los supuestos del modelo heurístico._
- El impacto se expresa como reducción del déficit estimado respecto al nivel de
  seguridad, no como medición de campo.

## 5. Qué no podemos afirmar

- No observamos los intentos frustrados: la demanda real puede ser mayor.
- Una predicción no garantiza disponibilidad futura.
- El rebalanceo no modela rutas, tiempos ni costos reales de la operación.
- La cobertura GBFS solo existe desde que se enciende el colector.

---

_Para reemplazar los `PENDIENTE` por cifras reales: descarga el histórico
(`make download LATEST=…`), normaliza, corre `run_pipeline.py --full` y relee la
app y `reports/`._
