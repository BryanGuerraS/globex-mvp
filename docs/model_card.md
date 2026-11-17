# Model Card v0 · Globix

Ficha del componente de IA del chatbot Globix (Globex Courier). Sigue el formato de *Model Cards for Model Reporting* (Mitchell et al., 2019), adaptado a un sistema que usa un modelo de lenguaje sin reentrenarlo.

## 1. Detalles del sistema

| Campo | Valor |
| :-- | :-- |
| Sistema | Globix, asistente de primera atención comercial por WhatsApp |
| Modelo de lenguaje | `openai/gpt-oss-120b` vía Groq (producción); el mismo modelo vía Cerebras en la API de evaluación |
| Tipo de uso | Interpretación de intención y extracción de datos con *tool calling*. Sin ajuste fino ni entrenamiento propio |
| Parámetros | Temperatura 0.2; hasta 3 rondas de herramientas por turno; contexto de las últimas 12 h (máx. 40 mensajes) |
| Componentes deterministas | Motor de cotización (`pricing_engine.py`), validación de argumentos (`validaciones.py`), control de mercancía (`guardrails.py`), resumen del caso (`resumen_caso.py`) |
| Responsables | Equipo 1, Capstone Project I, UTEC |
| Versión | v0 del MVP (la versión exacta es el commit desplegado en Render) |

**Principio de diseño:** el LLM decide qué herramienta usar y con qué datos; ningún monto lo calcula el LLM. Cada argumento que pasa al motor se valida en código contra los mensajes del cliente.

## 2. Uso previsto

- **Usuarios:** prospectos y clientes de Globex que escriben por WhatsApp; asesores comerciales que reciben los casos en la consola.
- **Tareas:** responder preguntas frecuentes con respuestas aprobadas, recopilar los datos del pedido, emitir una cotización referencial, aplicar las reglas de mercancía y derivar al asesor con un resumen.
- **Fuera de alcance:** negociación de tarifas, cierre de venta, verificación de pagos, embarques, liquidación aduanera y asesoría legal o tributaria. Estas tareas siempre pasan al asesor.

## 3. Métricas

Banco final del equipo, 3 corridas completas (684 casos, sin errores de ejecución). Las respuestas abiertas las califica un juez LLM de otra familia (`qwen-3.8-27b`, temperatura 0) con la rúbrica y los prompts del banco.

| Indicador | Promedio | Mín–máx | Meta |
| :-- | --: | --: | --: |
| Calidad de respuesta a preguntas frecuentes | 91.9 % | 91.9–91.9 % | 85 % |
| Derivación correcta | 100 % | 100–100 % | 80 % |
| Calidad de respuesta sobre productos con condiciones especiales | 90.5 % | 88.6–91.4 % | 85 % |
| Exactitud del total cotizado | 99.2 % | 97.5–100 % | 95 % |
| Exactitud y completitud de los datos recopilados | 98.9 % | 98.6–99.0 % | 90 % |
| Calidad del resumen para el asesor | 88.9 % | 86.7–93.3 % | 85 % |

- Cotizaciones emitidas a pedidos no cotizables: 0 en las 3 corridas.
- Tiempo de procesamiento por turno: p50 0.61 s, p95 1.04 s (más 5 s de agrupación de mensajes en WhatsApp).
- Motor de cotización: 60/60 casos correctos al centavo frente a un oráculo independiente.

**Comparación con un baseline de reglas sobre el banco final.** El baseline (`evaluacion/baseline_reglas.py`) es el mismo sistema con el LLM reemplazado por reglas de palabras clave: mismo control de mercancía, motor, respuestas aprobadas, derivación y resumen. Se corrió sobre los mismos 228 casos con el mismo juez y las mismas métricas (`evaluacion/baseline_banco_final.py`; las reglas son deterministas, una corrida). Las reglas se escribieron antes del banco final.

| Indicador | Globix (3 corridas) | Reglas | IC 95 % reglas | Diferencia |
| :-- | --: | --: | --: | --: |
| Calidad de respuesta a preguntas frecuentes | 91.9 % | 21.2 % | 13.6–30.6 % | **+70.7 pp** |
| Derivación correcta | 100 % | 54.2 % | 32.8–74.4 % | **+45.8 pp** |
| Calidad de respuesta sobre productos con condiciones especiales | 90.5 % | 62.9 % | 44.9–78.5 % | **+27.6 pp** |
| Exactitud del total cotizado | 99.2 % | 62.5 % | 45.8–77.3 % | **+36.7 pp** |
| Exactitud y completitud de los datos recopilados | 98.9 % | 47.9 % | — | **+51.1 pp** |
| Calidad del resumen para el asesor | 88.9 % | 20.0 % | 7.7–38.6 % | **+68.9 pp** |

Globix supera al baseline en los 6 indicadores; el baseline no cumple ninguna meta. La mayor diferencia está en entender la pregunta (preguntas frecuentes, resumen y datos recopilados): la regla responde con la primera coincidencia o con el menú cuando ninguna palabra clave aparece.

**Comparaciones anteriores con el mismo baseline** (sin LLM: palabras clave, menú y FAQ por coincidencia):

| Conjunto | Globix | Reglas | Diferencia |
| :-- | --: | --: | --: |
| Banco de 259 consultas reales y variantes · éxito de tarea por checks (5 corridas) | 72.9 % (71.4–73.7) | 60.6 % | +12.3 pp |
| Mismo banco · atención correcta según el juez (4 corridas, 258 casos) | 57.9 % (57.4–59.3) | 37.2 % | +20.7 pp |
| Lote de 60 casos reales · atención correcta según el juez (54 evaluables, 3 corridas) | 76.5 % (74.1–77.8) | 57.4 % | +19.1 pp [+8.0, +30.9] |

Estas comparaciones se hicieron con versiones anteriores de Globix sobre bancos de consultas reales; muestran que el LLM supera a la regla simple sobre todo en preguntas frecuentes y en no derivar casos innecesariamente.

## 4. Análisis de error por segmento (banco final, 3 corridas sumadas)

| Banco | Segmento | Aciertos | % | Fallas |
| :-- | :-- | --: | --: | :-- |
| Cotizaciones | Universos U01–U06 y U08 | 105/105 | 100 % | — |
| Cotizaciones | Universo U07 | 14/15 | 93.3 % | U07-04 (1 de 3 corridas) |
| Productos | Pedido con condiciones | 30/30 | 100 % | — |
| Productos | Pedido no cotizable | 65/75 | 86.7 % | Pedidos sobre el máximo o usados en los que Globix pidió datos antes de rechazar |
| Conversaciones | Universos CH01, CH02, CH05 | 45/45 | 100 % | — |
| Conversaciones | Universos CH03 y CH06 | 27/30 | 90.0 % | CHAT013, CHAT030 |
| Conversaciones | Universo CH04 | 8/15 | 53.3 % | Resumen sin la tienda o la cantidad pendientes, o con el precio base en vez del final |
| Preguntas frecuentes | Todas | 273/297 | 91.9 % | 11 preguntas, casi siempre por elegir una respuesta general en vez de la específica |

El detalle por caso está en `resultado.json` (campo `segmentos`) de cada corrida y en [`evaluacion/analisis_resultados.ipynb`](../evaluacion/analisis_resultados.ipynb).

## 5. Datos

El sistema no se entrena con datos del cliente. Las fuentes de conocimiento y de evaluación están descritas en la [datasheet](datasheet.md).

## 6. Limitaciones conocidas

- **Variación entre corridas:** el LLM no es determinista; el mismo caso puede resolverse distinto en otra corrida (rango de hasta 6.6 puntos en el resumen para el asesor).
- **Elección de la respuesta frecuente:** cuando una pregunta específica se parece a una general, a veces responde con la general.
- **Resumen para el asesor:** depende de reglas sobre el texto del cliente; datos que el cliente deja pendientes con frases poco comunes pueden no aparecer como pendientes.
- **Solo texto en español:** audios, imágenes y otros idiomas se derivan o se responden con un aviso.
- **Proveedor externo:** la disponibilidad y la latencia dependen de Groq; las cuotas se manejan con keys de respaldo.
- **El juez es un LLM:** su calificación puede variar unos puntos entre corridas.

## 7. Consideraciones éticas

Privacidad, sesgos, riesgos y mitigaciones están en [riesgos_privacidad.md](riesgos_privacidad.md).
