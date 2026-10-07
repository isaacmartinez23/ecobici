# Memo ejecutivo — ECOBICI: dónde faltan bicicletas y a qué hora

**Para**: persona que decide presupuesto de operación.
**De**: equipo de datos.
**Fecha del análisis**: 2026-10-07.
**Datos**: histórico real de ECOBICI, **julio–septiembre 2026** (3 meses;
primera marca 2026-06-30 por cruces de medianoche). Disponibilidad GBFS: **una
sola captura** del 2026-10-07 (el colector apenas se encendió). Las cifras del
modelo y de demanda son reales; las de disponibilidad/rebalanceo son estimaciones
condicionadas a esa captura única (ver §5).

---

## 1. Qué preguntamos

¿Qué estaciones se quedan sin bicicletas, en qué días y horas, y cuántas bicis
convendría mover —y desde dónde— para reducir el desabasto?

## 2. Qué encontramos

- **Volumen**: 4,464,138 viajes válidos en 679 estaciones de origen. Calidad del
  histórico muy alta: solo **0.044 %** descartado (1,963 viajes), por duración
  fuera de rango (1,320 > 240 min; 643 < 1 min). Sin duplicados ni fechas
  inválidas.
- **Cuándo aprieta**: la demanda (salidas atendidas por estación y hora) tiene
  **dos picos entre semana**: mañana a las **08:00** (~5.9 salidas/h por estación)
  y tarde **17:00–18:00** (~5.6–5.8). El fin de semana cae ~30 % (≈3.1–3.3 vs.
  ≈4.3–4.65 salidas/h entre semana).
- **Dónde se vacían**: las estaciones con mayor **presión de vaciado** (flujo neto
  acumulado más negativo = muchas más salidas que llegadas) incluyen, entre las
  emparejadas con GBFS: **CE-278 Mier y Pesado–Obrero Mundial**,
  **CE-703 Miguel Hidalgo–Calzada General Anaya**,
  **CE-294 Nicolás San Juan–Eje 4 Sur Xola** y
  **CE-540 Eucalipto–Ricardo Flores Magón**. Otras estaciones de alto drenaje
  usan IDs históricos compuestos (p. ej. 237-238, 390-391) que no tienen
  contraparte directa en GBFS.
- **Modelo vs. línea base** (partición temporal; prueba = 12–30 sep 2026,
  n = 300,560 observaciones estación-hora):

  | Métrica | Línea base | Modelo | Cambio |
  |---|---|---|---|
  | MAE (salidas/h) | 1.534 | 1.501 | −2.2 % |
  | RMSE | 2.745 | 2.535 | **−7.7 %** |
  | WAPE | 0.508 | 0.497 | −1.1 pp |
  | Sesgo medio | −0.259 | **−0.010** | casi insesgado |

  El modelo gana sobre todo en **RMSE** (menos errores grandes) y en **sesgo**
  (deja de subestimar). En **horas pico** también mejora: MAE 2.355 → 2.255,
  RMSE 3.77 → 3.43.

## 3. Qué recomendamos hacer

- Priorizar el reabasto de las estaciones receptoras en las **franjas pico
  (08:00 y 17:00–18:00) entre semana**, tomando bicis de donantes cercanas por
  encima de su nivel objetivo.
- Movimientos concretos (donante→receptora, bicis, distancia): tabla descargable
  en la sección **Rebalanceo** de la app. Para la ventana objetivo evaluada
  (2026-10-07 18:00): **117 movimientos**, **594 bicicletas**, entre
  **96 estaciones donantes** y **314 receptoras** con déficit.

## 4. Qué impacto estimamos

- Déficit estimado respecto al nivel de seguridad: **886.5 → 686.0 bicis**
  tras el rebalanceo propuesto ⇒ **≈22.6 % del desabasto estimado evitado** en
  esa ventana (inventario total conservado; ninguna donante queda por debajo de
  su nivel de seguridad).
- El impacto se expresa como reducción del déficit estimado, no como medición de
  campo.

## 5. Qué no podemos afirmar

- Los 4.46 M de viajes son **demanda atendida**: donde la estación ya está vacía,
  los intentos frustrados **no se observan**, así que la demanda real en las
  estaciones de alto drenaje está **subestimada**.
- La **disponibilidad GBFS** proviene de **una sola captura** (2026-10-07): aún no
  permite un ranking de "minutos sin bicis" ni validar los faltantes reales; la
  presión de vaciado de §2 se infiere del flujo neto histórico, no de stockouts
  observados. Hace falta acumular capturas (cada 5 min) para medir disponibilidad.
- El **puente de estaciones** cubre **79 % de las estaciones** y **54.7 % de los
  viajes** (emparejamiento por ID exacto; 143 estaciones históricas sin
  contraparte GBFS). El análisis ligado a GBFS (mapa, rebalanceo) se limita a esa
  cobertura.
- Una **predicción no garantiza** disponibilidad futura; el modelo no incorpora
  clima, tráfico ni costo de traslado.
- El **rebalanceo** es una estimación con los supuestos anteriores; no modela
  rutas, tiempos ni capacidad de los vehículos.

---

_Reproducción: `download_historical --months 2026-07,2026-08,2026-09` →
`normalize_historical` → `collect_gbfs` → `run_pipeline.py --full`. Las cifras
cambian con el periodo descargado; este memo corresponde a jul–sep 2026._
