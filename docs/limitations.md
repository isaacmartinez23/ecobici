# Limitaciones

## Naturaleza de los datos

- **Demanda atendida ≠ demanda real.** Los viajes del histórico son retiros que
  efectivamente ocurrieron. Cuando una estación está vacía, los intentos
  frustrados no quedan registrados. Por tanto, en estaciones con vaciado
  frecuente, la demanda real está **subestimada**.
- **GBFS es una fotografía.** El feed no contiene historia. La disponibilidad solo
  existe desde que se enciende el colector; no hay reconstrucción del pasado.
- **Cobertura del puente.** Los IDs del histórico y de GBFS pueden divergir. El
  histórico de viajes no trae nombre ni coordenadas de estación, por lo que el
  emparejamiento por nombre/geografía requiere un catálogo externo; en su ausencia
  domina la coincidencia exacta de ID y algunos IDs pueden quedar sin emparejar.

## Modelo

- Predice **demanda atendida**, no demanda latente. Una predicción **no garantiza**
  disponibilidad futura de bicicletas.
- No incorpora clima, tráfico, eventos, costo de traslado ni restricciones
  operativas completas, salvo que existan datos reales y reproducibles para ello.
- La incertidumbre no se modela explícitamente (se reportan predicciones puntuales
  de línea base y modelo).
- El horizonte por defecto es de una hora; horizontes largos degradan la calidad.

## Rebalanceo

- Es una **estimación heurística**, no una prescripción operativa. Usa el
  inventario esperado (inventario de referencia menos flujo neto esperado) y
  emparejamiento greedy por cercanía.
- No modela rutas reales de los camiones, ventanas de tiempo, capacidad del
  vehículo ni costos; el emparejamiento por distancia en línea recta es una
  aproximación.
- El "porcentaje de desabasto evitado" se calcula respecto al déficit estimado
  bajo los supuestos anteriores; no es una medición de campo.

## Datos de muestra

- Los datos por defecto (`data/sample/`) son **sintéticos y deterministas**.
  Sirven para demostrar y probar el pipeline. **Las métricas mostradas con la
  muestra no son conclusiones sobre ECOBICI real.**

## Automatización

- GitHub Actions **no garantiza** precisión de 5 minutos en los crons y sus
  runners son efímeros. La persistencia por defecto (artefactos) tiene retención
  limitada; para historia durable se documentan alternativas (S3, base gestionada,
  rama de datos) en el workflow.
