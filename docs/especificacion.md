> **Nota**: Este documento es la _especificación original_ del proyecto: el
> enunciado que definió el alcance, la arquitectura y los criterios de
> aceptación. Se conserva como referencia. La documentación viva del proyecto
> está en el [README](../README.md) y en el resto de `docs/`.

---

Actúa como un Data Engineer y Data Scientist senior especializado en Python, DuckDB, series temporales, datos geoespaciales y aplicaciones de datos con Streamlit.

Tu tarea es construir, probar y documentar de principio a fin un proyecto de portafolio llamado:

“ECOBICI: dónde faltan bicicletas y a qué hora”

## 1. Objetivo del proyecto

Desarrolla un sistema reproducible que permita responder:

- ¿Qué estaciones de ECOBICI tienen mayor riesgo de quedarse sin bicicletas?
- ¿En qué días y franjas horarias sucede?
- ¿Qué estaciones acumulan bicicletas y pueden funcionar como estaciones donantes?
- ¿Cuántas bicicletas convendría mover?
- ¿Desde qué estaciones y hacia cuáles?
- ¿Qué porcentaje del desabasto estimado podría evitarse mediante el rebalanceo?

El proyecto debe combinar:

1. Histórico mensual de viajes de ECOBICI.
2. Disponibilidad en tiempo real obtenida mediante GBFS.
3. Una línea base estadística.
4. Un modelo predictivo de demanda.
5. Un algoritmo de recomendación de rebalanceo.
6. Una aplicación interactiva en Streamlit.
7. Pruebas de calidad de datos.
8. Documentación técnica y ejecutiva.

No inventes resultados, métricas, archivos descargados ni conclusiones. Si todavía no hay suficientes datos, deja la infraestructura preparada y muestra claramente qué resultados están pendientes.

## 2. Fuentes de datos

### Histórico de viajes

Fuente principal:

https://ecobici.cdmx.gob.mx/en/open-data/

Los archivos CSV se publican mensualmente. No construyas sus URLs mediante una fórmula porque la carpeta de publicación puede ser distinta al mes contenido en el archivo.

Implementa un scraper que:

- Extraiga los enlaces reales de descarga desde la página.
- Identifique, cuando sea posible, año y mes del conjunto.
- Guarde un manifiesto en `data/manifests/ecobici_historico.csv`.
- Registre URL, nombre del archivo, fecha de descubrimiento, estado de descarga, tamaño y checksum.
- Evite volver a descargar archivos sin cambios.
- Permita elegir un rango de meses.
- Maneje ZIP, CSV, codificaciones distintas y errores HTTP.
- Use reintentos, timeout y logging.
- No incluya los archivos crudos en Git.

Columnas históricas esperadas, aunque pueden cambiar entre años:

- Genero_Usuario
- Edad_Usuario
- Bici
- Ciclo_Estacion_Retiro
- Fecha_Retiro
- Hora_Retiro
- Ciclo_Estacion_Arribo
- Fecha_Arribo
- Hora_Arribo

Crea una capa de normalización que soporte diferencias de nombres, tipos y formatos entre años. No asumas que todos los archivos tienen el mismo esquema.

### Datos GBFS

Discovery feed:

https://gbfs.mex.lyftbikes.com/gbfs/gbfs.json

Utiliza al menos:

- `station_information`
- `station_status`
- `system_information`

El feed GBFS es una fotografía del momento y no contiene historia. Por eso, implementa desde el inicio un colector que guarde `station_status` cada cinco minutos.

Cada captura debe conservar, como mínimo:

- `capturado_en_utc`
- `capturado_en_local`
- `station_id`
- `num_bikes_available`
- `num_docks_available`
- `is_installed`
- `is_renting`
- `is_returning`
- `last_reported`
- fecha de ingestión
- identificador de ejecución

Usa la zona horaria `America/Mexico_City`.

Evita insertar dos veces la misma captura. Agrega controles para respuestas incompletas, estaciones duplicadas, valores negativos y fallas temporales.

## 3. Tecnologías

Utiliza:

- Python 3.11 o superior.
- DuckDB como motor analítico local.
- Pandas o Polars para transformaciones.
- Requests y BeautifulSoup para ingestión.
- PyArrow y Parquet cuando sea conveniente.
- Scikit-learn para métricas y pipelines.
- LightGBM si está disponible.
- Una alternativa basada en scikit-learn si LightGBM no puede instalarse.
- GeoPandas para operaciones espaciales.
- Plotly y PyDeck o Folium para visualizaciones.
- Streamlit para la aplicación.
- Pytest para pruebas.
- Ruff para linting.
- Makefile para automatización.
- GitHub Actions para pruebas y ejecución programada del colector.

Administra dependencias mediante `pyproject.toml`. Genera también un `requirements.txt` compatible si ayuda al despliegue.

No uses servicios de pago ni dependencias que requieran credenciales para ejecutar la versión básica.

## 4. Estructura del repositorio

Crea esta estructura:

ecobici-demanda/
├── README.md
├── Makefile
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── .env.example
├── .pre-commit-config.yaml
├── app/
│   ├── app.py
│   ├── components/
│   └── utils/
├── config/
│   ├── settings.yaml
│   └── station_aliases.csv
├── data/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   ├── manifests/
│   └── sample/
├── ingest/
│   ├── scrape_historical_urls.py
│   ├── download_historical.py
│   ├── collect_gbfs.py
│   └── load_raw_to_duckdb.py
├── transform/
│   ├── normalize_historical.py
│   ├── build_station_bridge.py
│   ├── build_trip_facts.sql
│   ├── demand_by_hour.sql
│   ├── availability_by_hour.sql
│   └── build_features.py
├── models/
│   ├── baseline.py
│   ├── train.py
│   ├── evaluate.py
│   ├── predict.py
│   └── rebalance.py
├── analysis/
│   └── README.md
├── reports/
│   ├── figures/
│   └── memo.md
├── docs/
│   ├── architecture.md
│   ├── data_dictionary.md
│   ├── decisions.md
│   └── limitations.md
├── tests/
│   ├── test_ingestion.py
│   ├── test_normalization.py
│   ├── test_data_quality.py
│   ├── test_features.py
│   └── test_rebalance.py
└── .github/
    └── workflows/
        ├── ci.yml
        └── collect_gbfs.yml

Puedes agregar archivos si son necesarios, pero conserva esta organización general.

## 5. Base de datos DuckDB

Crea `data/ecobici.duckdb` localmente y exclúyelo de Git.

Diseña, como mínimo, las siguientes tablas:

- `ingestion_runs`
- `historical_file_manifest`
- `trips_raw`
- `trips_clean`
- `trip_rejections`
- `station_information`
- `station_status`
- `station_bridge`
- `demand_hourly`
- `availability_hourly`
- `model_features`
- `model_predictions`
- `rebalance_recommendations`

Incluye scripts idempotentes para crear y actualizar las tablas.

Documenta para cada tabla:

- Grano.
- Llave primaria o llave lógica.
- Columnas.
- Tipos.
- Fuente.
- Reglas de calidad.

## 6. Limpieza del histórico

Normaliza nombres de columnas a `snake_case`.

Construye correctamente las marcas de tiempo de retiro y arribo. Debido a que los formatos pueden cambiar, crea un parser robusto que pruebe explícitamente un conjunto documentado de formatos.

No uses inferencias silenciosas que puedan intercambiar día y mes.

Clasifica y registra los rechazos, en lugar de borrarlos sin explicación. Considera al menos:

- Fecha u hora inválida.
- Llegada anterior o igual al retiro.
- Duración menor a un minuto.
- Duración mayor a 240 minutos.
- Estación de origen ausente.
- Estación de destino ausente.
- Identificador de bicicleta ausente, cuando sea relevante.
- Registro duplicado.

Calcula y reporta:

- Número total de filas.
- Filas válidas.
- Filas rechazadas.
- Porcentaje rechazado.
- Rechazos por motivo.
- Rechazos por archivo y periodo.

## 7. Tabla puente de estaciones

Los identificadores del histórico y de GBFS pueden no coincidir.

Construye `station_bridge` usando:

1. Coincidencia exacta de identificador.
2. Normalización de nombres.
3. Coincidencia aproximada de nombres.
4. Distancia geográfica entre coordenadas.
5. Archivo manual de excepciones en `config/station_aliases.csv`.

Cada correspondencia debe conservar:

- ID histórico.
- ID GBFS.
- Nombre histórico.
- Nombre GBFS.
- Latitud y longitud.
- Método de emparejamiento.
- Puntaje de confianza.
- Distancia en metros.
- Indicador de revisión manual.

Reporta el porcentaje de estaciones y viajes cubiertos por el puente. No aceptes automáticamente coincidencias ambiguas.

## 8. Agregación de demanda

Calcula por estación y hora:

- Salidas.
- Llegadas.
- Flujo neto.
- Demanda atendida.
- Disponibilidad inicial y final, cuando existan capturas GBFS.
- Mínimo de bicicletas disponibles.
- Máximo de bicicletas disponibles.
- Minutos estimados con cero bicicletas.
- Minutos estimados sin anclajes.
- Indicadores de estación vacía o llena.

La lógica base debe reflejar:

`flujo_neto = llegadas - salidas`

Un flujo neto negativo sostenido indica presión de vaciado, pero no equivale por sí solo a demanda real no atendida.

Declara expresamente que los viajes observados representan demanda atendida. Cuando una estación está vacía, las salidas que las personas intentaron realizar no aparecen en el histórico.

## 9. Ingeniería de variables

Genera variables sin fuga temporal:

- Hora.
- Día de la semana.
- Fin de semana.
- Mes.
- Semana del año.
- Festivo.
- Quincena.
- Estación.
- Capacidad de la estación.
- Latitud y longitud.
- Salidas y llegadas rezagadas.
- Flujo neto rezagado.
- Medianas móviles.
- Promedios móviles.
- Disponibilidad reciente.
- Comportamiento de la misma estación a la misma hora durante semanas anteriores.

Todas las variables móviles y rezagadas deben utilizar exclusivamente información disponible antes del momento predicho.

Si no hay una fuente climática confiable y reproducible, no inventes datos de clima. Deja una interfaz opcional para incorporarlos posteriormente.

## 10. Línea base y modelo

Primero implementa una línea base:

- Mediana histórica por estación, día de semana y hora.
- Como respaldo, mediana por estación y hora.
- Como segundo respaldo, mediana global por hora.

Después implementa un modelo supervisado para predecir, por estación y franja:

- Salidas.
- Llegadas.
- Flujo neto o bicicletas requeridas.

Utiliza una partición estrictamente temporal. Por ejemplo:

- Entrenamiento: primeros meses.
- Validación: penúltimo periodo.
- Prueba: último periodo disponible.

Las fechas reales deben determinarse a partir de los datos descargados; no las inventes.

Evita cualquier división aleatoria para la evaluación principal.

Evalúa línea base y modelo con:

- MAE.
- RMSE.
- WAPE, cuando el denominador sea válido.
- Sesgo medio.
- Métricas por estación.
- Métricas por hora.
- Métricas para horas pico.
- Métricas para estaciones con mayor demanda.

Guarda los resultados en archivos CSV o Parquet y genera figuras.

Si el modelo no supera la línea base, repórtalo con honestidad. No manipules la selección de datos para hacer que el modelo parezca mejor.

## 11. Recomendación de rebalanceo

Implementa un algoritmo transparente y separable del modelo predictivo.

Para cada ventana operativa:

1. Estima el inventario esperado por estación.
2. Calcula un nivel mínimo de seguridad.
3. Identifica estaciones receptoras con déficit.
4. Identifica estaciones donantes con excedente.
5. Respeta la capacidad de las estaciones.
6. Evita dejar una estación donante por debajo de su nivel de seguridad.
7. Empareja donantes y receptoras considerando distancia y cantidad.
8. Calcula bicicletas recomendadas por movimiento.
9. Estima el déficit antes y después.
10. Estima el porcentaje de desabasto evitado.

Genera una tabla con:

- Fecha y hora objetivo.
- Estación donante.
- Estación receptora.
- Bicicletas por mover.
- Distancia estimada.
- Inventario previsto antes y después.
- Déficit previsto antes y después.
- Nivel de confianza.
- Versión del modelo.

Empieza con un algoritmo heurístico explicable. Si implementas optimización lineal, mantenla como una opción adicional y documenta su función objetivo y restricciones.

No presentes la recomendación como un hecho. Etiquétala como estimación del modelo.

## 12. Aplicación Streamlit

Construye una aplicación profesional en español con estas secciones:

### Resumen ejecutivo

- Periodo analizado.
- Número de viajes.
- Número de estaciones.
- Porcentaje de registros descartados.
- Estaciones con mayor riesgo.
- Comparación entre línea base y modelo.

### Mapa interactivo

- Marcadores por estación.
- Color según riesgo de vaciado o saturación.
- Tamaño según demanda.
- Tooltip con métricas principales.
- Selector de fecha.
- Slider de hora.
- Filtros por día de semana y nivel de riesgo.

### Demanda por estación

- Salidas y llegadas por hora.
- Flujo neto.
- Disponibilidad observada.
- Predicción.
- Intervalo o medida de incertidumbre si está disponible.

### Rebalanceo

- Tabla de movimientos recomendados.
- Mapa con líneas entre estaciones donantes y receptoras.
- Bicicletas por mover.
- Déficit estimado antes y después.
- Descarga de recomendaciones en CSV.

### Calidad y limitaciones

- Cobertura GBFS.
- Datos faltantes.
- Porcentaje descartado.
- Cobertura del puente de estaciones.
- Limitaciones del modelo.
- Diferencia entre demanda atendida y demanda real.

La aplicación debe funcionar también con datos de muestra incluidos en `data/sample/`.

## 13. Automatización

Crea un `Makefile` con, al menos:

- `make setup`
- `make scrape`
- `make download`
- `make collect-gbfs`
- `make ingest`
- `make transform`
- `make features`
- `make train`
- `make evaluate`
- `make recommend`
- `make app`
- `make test`
- `make lint`
- `make all`
- `make clean`

Los comandos principales para reproducir el proyecto deben ser:

`make setup`
`make all`

`make all` debe poder ejecutarse con datos de muestra cuando no se solicite explícitamente la descarga completa.

Configura GitHub Actions para:

1. Ejecutar lint y pruebas en cada push o pull request.
2. Ejecutar el colector GBFS cada cinco minutos, siempre que las restricciones reales de GitHub Actions lo permitan.
3. Permitir ejecución manual.
4. Guardar o transferir los datos persistentes de manera segura.

Importante: documenta que GitHub Actions no garantiza precisión exacta de cinco minutos y que sus runners son efímeros. No confíes únicamente en el sistema de archivos del runner para conservar el histórico. Implementa una estrategia configurable de persistencia y explica las opciones.

No subas secretos al repositorio.

## 14. Calidad de software y datos

Incluye:

- Type hints.
- Docstrings útiles.
- Logging estructurado.
- Manejo explícito de excepciones.
- Configuración centralizada.
- Funciones pequeñas y reutilizables.
- Consultas SQL legibles.
- Pruebas unitarias.
- Pruebas de integración mínimas.
- Datos sintéticos para probar casos límite.
- Semillas aleatorias configuradas cuando correspondan.

Prueba, como mínimo:

- Parsing de fechas.
- Normalización de columnas.
- Detección de duplicados.
- Reglas de descarte.
- Idempotencia del colector.
- Variables rezagadas sin fuga temporal.
- Respeto de capacidad en el rebalanceo.
- Conservación del inventario trasladado.
- Imposibilidad de mover cantidades negativas.
- Comportamiento cuando no existen donantes suficientes.

## 15. Documentación

El `README.md` debe incluir:

- Pregunta de negocio.
- Respuesta corta, únicamente cuando existan resultados reales.
- Arquitectura.
- Fuentes y cobertura.
- Cómo reproducir.
- Cómo activar el colector.
- Cómo ejecutar Streamlit.
- Método.
- Reglas de limpieza.
- Comparación línea base vs. modelo.
- Hallazgos con fecha y unidad.
- Recomendación de rebalanceo.
- Limitaciones.
- Estructura del repositorio.
- Diccionario de datos.
- Próximos pasos.

Incluye una sección exacta titulada:

“Lo que este análisis NO puede decir”

Debe explicar, como mínimo:

- Los viajes representan demanda atendida.
- No se observan directamente los intentos frustrados.
- La cobertura GBFS comienza cuando se enciende el colector.
- Una predicción no garantiza disponibilidad futura.
- El modelo no incorpora tráfico, costo de traslado ni restricciones completas de operación, salvo que existan datos reales para ello.

Crea también:

- `docs/architecture.md`
- `docs/data_dictionary.md`
- `docs/decisions.md`
- `docs/limitations.md`
- `reports/memo.md`

El memo debe estar dirigido a una persona que decide presupuesto y seguir esta estructura:

1. Qué preguntamos.
2. Qué encontramos.
3. Qué recomendamos hacer.
4. Qué impacto estimamos.
5. Qué no podemos afirmar.

No inventes el contenido cuantitativo del memo. Usa marcadores claramente identificados hasta que el pipeline produzca resultados reales.

## 16. Git y reproducibilidad

Configura `.gitignore` para excluir:

- `.env`
- entornos virtuales
- bases DuckDB
- modelos generados
- datos crudos
- datos intermedios
- resultados pesados
- cachés
- archivos temporales

Sí incluye:

- Código.
- Configuraciones sin secretos.
- Manifiestos sin información sensible.
- Datos de muestra pequeños.
- Documentación.
- Pruebas.
- Esquemas.
- Archivos de dependencias.

El repositorio debe ser liviano y reconstruible. Guarda scripts de descarga, no cientos de megabytes de datos.

## 17. Forma de trabajo

Trabaja de manera autónoma y ordenada:

1. Inspecciona primero el directorio actual.
2. Si ya existe código, no lo sobrescribas sin revisarlo.
3. Presenta un plan breve.
4. Construye el proyecto por etapas.
5. Después de cada etapa, ejecuta las pruebas correspondientes.
6. Corrige los errores antes de continuar.
7. No afirmes que algo funciona sin ejecutarlo.
8. Si el acceso a internet está deshabilitado, utiliza fixtures y datos sintéticos, pero deja los scripts reales implementados.
9. No detengas todo el proyecto por falta de datos externos.
10. Registra decisiones importantes en `docs/decisions.md`.
11. Mantén una lista de pendientes.
12. Al finalizar, ejecuta:
    - lint
    - pruebas
    - pipeline con datos de muestra
    - verificación de arranque de Streamlit

No crees únicamente plantillas vacías. Implementa una versión mínima funcional de cada componente.

## 18. Orden de implementación

Sigue este orden:

Fase 1:
- Estructura del repositorio.
- Configuración.
- Base de datos.
- Colector GBFS.
- Pruebas del colector.

Fase 2:
- Scraper del histórico.
- Descargador.
- Normalización de esquemas.
- Reglas de limpieza.
- Reporte de rechazos.

Fase 3:
- Tabla puente de estaciones.
- Agregaciones por hora.
- Variables predictivas.
- Controles contra fuga temporal.

Fase 4:
- Línea base.
- Modelo.
- Evaluación temporal.
- Comparación de resultados.

Fase 5:
- Algoritmo de rebalanceo.
- Streamlit.
- Documentación.
- GitHub Actions.
- Revisión final.

## 19. Criterios de aceptación

El proyecto estará terminado cuando:

- `make setup` funciona.
- `make all` funciona con datos de muestra.
- El colector GBFS guarda capturas idempotentes.
- El histórico se normaliza sin depender de un único esquema.
- Los registros descartados quedan cuantificados por causa.
- Existe una tabla puente auditable de estaciones.
- Las variables temporales no presentan fuga.
- El modelo se compara contra una línea base.
- Las métricas se calculan sobre una partición temporal.
- El rebalanceo respeta capacidad, inventario y niveles de seguridad.
- La aplicación Streamlit inicia sin errores.
- Las pruebas pasan.
- El README permite reproducir el proyecto.
- Las limitaciones están documentadas.
- No hay secretos ni datos crudos pesados en Git.

## 20. Entrega final

Al terminar:

1. Resume lo que implementaste.
2. Muestra la estructura final del repositorio.
3. Enumera los comandos para ejecutarlo.
4. Indica qué pruebas ejecutaste y sus resultados.
5. Explica qué componentes usan datos reales y cuáles datos de muestra.
6. Señala cualquier limitación o pendiente.
7. No presentes métricas inventadas.
8. Propón los siguientes tres pasos con mayor impacto.

Comienza inspeccionando el directorio y creando un plan de implementación. Después procede a construir el proyecto sin esperar confirmación, salvo que encuentres una decisión que pueda borrar o sobrescribir trabajo existente.