# Datasheet · datos de Globix

Ficha de los datos que usa y con los que se evaluó Globix, según *Datasheets for Datasets* (Gebru et al., 2021). Cada fuente indica si es **real**, **derivada de datos reales** o **sintética**.

## 1. Inventario

| # | Fuente | Tipo | Contenido | Uso | En el repositorio |
| :-: | :-- | :-- | :-- | :-- | :-- |
| D1 | Exportaciones de WhatsApp de Globex (4 cuentas) | Real | 10 511 instancias chat-cuenta y 7 058 leads | Línea base del KPI (32 % con primera respuesta útil en ≤ 60 min), dimensionamiento y diseño de los bancos | **No**: contienen datos personales |
| D2 | Base de conocimiento de 132 respuestas | Derivada de datos reales | Preguntas y respuestas comerciales redactadas por el equipo con información de Globex | Respuestas frecuentes de Globix (se envían tal cual) | Sí: `conocimiento/` |
| D3 | Respuestas del menú | Derivada de datos reales | Dirección en Miami, plazos, entregas, provincias, pagos, cómo funciona, viajero | Menú *Otras consultas* | Sí: `knowledge_base.py` |
| D4 | Reglas de cotización y de mercancía | Real (reglas del negocio) | Tarifas, tributos, tope, prohibidos, máximos por categoría | Motor y control de mercancía | Sí: `pricing_engine.py`, `guardrails.py` |
| D5 | Catálogo de pesos referenciales | Sintética (curada) | Peso aproximado con empaque de 13 productos frecuentes | Estimar el peso cuando el cliente no lo da (se marca como estimado) | Sí: `product_catalog.py` |
| D6 | Casos del motor | Sintética | 60 casos con su resultado calculado por un oráculo independiente | Verificación al centavo del motor | Sí: `evaluacion/casos_motor.json` |
| D7 | Set de desarrollo | Sintética | 173 conversaciones guionadas con el resultado esperado | Probar y ajustar el comportamiento | Sí: `evaluacion/casos_desarrollo.json` |
| D8 | Banco de consultas reales y variantes | Real y variantes | 267 casos: 79 consultas reales, 158 variantes y 30 controles | Comparación con el baseline de reglas | No: reservado |
| D9 | Lote de casos reales | Real | 60 consultas de leads distintos de D8 | Comparación de versiones y con el baseline | No: reservado |
| D10 | Banco final del equipo | Construido por el equipo | 228 casos en 5 bancos (preguntas frecuentes, derivación, productos, cotizaciones y conversaciones) con referencias y prompts del juez | Evaluación final de los 6 indicadores | No: se entrega aparte con su manifiesto SHA-256 |

## 2. Recolección y preparación

- **D1** son exportaciones de las cuentas de WhatsApp proporcionadas por Globex. Se usa de forma agregada; ningún mensaje real se publica en el repositorio.
- **D8 y D9** son consultas reales de leads, usadas solo para evaluación y fuera del repositorio. Las variantes de D8 parafrasean consultas reales.
- **D10** se congeló antes de la evaluación: cada archivo tiene su hash en `MANIFIESTO_SHA256.txt` y `evaluacion.py` se detiene si alguno cambió.
- Los conjuntos sintéticos (D5, D6, D7) se identifican como tales en su nombre y su documentación.

## 3. Calidad y validación

- **Motor:** los resultados esperados de D6 salen de un oráculo en `Decimal` escrito aparte del motor.
- **Evaluación sin fuga:** cada caso se ejecuta en una conversación nueva, sin historial de otros casos ni acceso a la respuesta esperada; el juez recibe la referencia solo después de que Globix responde.
- **Juez:** otra familia de modelo que Globix, temperatura 0, con la rúbrica del banco.

## 4. Datos que guarda el sistema en operación

| Dato | Para qué | Dónde |
| :-- | :-- | :-- |
| ID de usuario de Meta (BSUID) | Identificar la conversación | `chats.chat_id` |
| Teléfono (si Meta lo comparte) | Solo como respaldo de envío; no se muestra | `chats.telefono` |
| Nombre (solo si el cliente lo da al derivar) | Atención del asesor y proforma | `chats.nombre_cliente` |
| Mensajes, cotizaciones y borrador del pedido | Atención y resumen del caso | SQLite (`globex.db`) |
| Métricas por turno | Costo, latencia y calidad | `metricas_turno` |

Retención: en el plan gratuito de Render la base se reinicia con cada despliegue. Los detalles de privacidad están en [riesgos_privacidad.md](riesgos_privacidad.md).

## 5. Limitaciones de los datos

- D7 lo escribió el propio equipo de desarrollo y sirvió para ajustar: no mide generalización.
- D5 son pesos aproximados; la proforma los marca como estimados.
- D10 tiene pocos casos por banco (24 a 99): los intervalos de confianza son amplios, sobre todo en derivación y en conversaciones.
