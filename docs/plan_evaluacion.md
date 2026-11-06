# Plan de evaluación del modelo: KPIs de calidad

**Estado:** propuesta para discutir en el equipo (04/11/2026).

**Por qué este plan:** el KPI de "primera atención útil en ≤ 60 min" mide sobre todo la disponibilidad del bot, que responde en segundos, y no si la respuesta fue correcta. Hace falta medir **qué tan bien decide el modelo**: si elige la herramienta correcta, si extrae bien los datos, si deriva cuando corresponde, si se mantiene en su alcance y si no inventa información.

---

## 1. Cómo evalúan otros chatbots con LLM

| Referencia | Qué mide | Qué tomamos |
| :-- | :-- | :-- |
| **τ-bench** (Sierra, 2024) | Un usuario simulado conversa con el agente. Una tarea es exitosa si el estado final (la base de datos) coincide con el esperado. Introduce **pass^k**: acertar en las *k* repeticiones de la misma tarea. GPT-4o tiene más de 60 % en pass^1 pero menos de 25 % en pass^8. | Éxito de tarea por desenlace verificable y consistencia pass^k |
| **τ²-bench** (2025) | Separa los errores de razonamiento del agente de los errores de comunicación con el usuario | Distinguir "decidió mal" de "preguntó mal" |
| **BFCL** (Berkeley) | Compara la llamada a herramienta contra la de referencia (nombre y argumentos) y si el modelo **se abstiene** cuando ninguna herramienta aplica | Exactitud de herramienta, de argumentos y "no cotizar indebidamente" |
| **Anthropic, *Demystifying evals for AI agents*** | Evaluadores por código, por modelo y humanos. Empezar con **20–50 tareas** sacadas de fallas reales. Separar evals de regresión (≈100 %) de evals de capacidad. | Tamaño del set y tipos de evaluador |
| **RAGAS: faithfulness** | Afirmaciones de la respuesta respaldadas por el contexto / total de afirmaciones | Fidelidad de las respuestas FAQ a `knowledge_base.py` |
| **OWASP Top 10 LLM** | Prompt injection (LLM01) y exceso de autonomía | Pruebas adversariales de alcance |
| **MT-Bench: LLM como juez** | Un juez LLM alcanza ~80 % de acuerdo con humanos, pero tiene sesgos de posición, verbosidad y autopreferencia | Usarlo solo si se valida con kappa contra la revisión humana |
| **Métricas de atención** (containment, escalation, fallback) | Resolución sin humano, tasa de derivación, respuestas de "no entendí" | Adaptadas: aquí **derivar bien es un acierto**, no un fracaso |

---

## 2. KPIs propuestos

**Unidad de medida:** conversaciones de un set reservado (n ≈ 30–60), con el desenlace esperado anotado antes de ejecutar. Cada KPI se reporta con su IC 95 % de Clopper-Pearson. Con n pequeño, el IC es la cifra que importa: 30/30 aciertos solo garantizan ≥ 88.4 %.

### A. Decisión y herramientas (automáticos contra la anotación)

| # | KPI | Definición | Meta orientativa |
| :-- | :-- | :-- | :-- |
| K1 | **Exactitud de herramienta** | Turnos en que el modelo llamó la herramienta esperada, o ninguna cuando no correspondía / turnos anotados | ≥ 90 % |
| K2 | **Exactitud de argumentos** | Llamadas a `calcular_cotizacion` con valor y peso iguales a lo que dijo el cliente / llamadas a `calcular_cotizacion` | ≥ 95 % |
| K3 | **Cotización indebida** (guardarraíl) | Cotizaciones emitidas cuando no correspondía (faltaban datos, valor > USD 1 200, mercancía restringida, dato inventado) / casos donde no correspondía cotizar | **0**, reportando el límite superior del IC |
| K4 | **Exactitud de derivación** | Derivaciones correctas / casos que debían derivarse. Contrapeso: derivaciones innecesarias / casos que no debían derivarse | ≥ 90 % y ≤ 10 % |
| K5 | **Recall del guardrail** | Mercancías restringidas detectadas / casos restringidos. Contrapeso: falsos positivos sobre productos permitidos | 100 % y ≤ 5 % |

### B. Calidad de la conversación (revisión humana doble, con kappa)

| # | KPI | Definición | Meta orientativa |
| :-- | :-- | :-- | :-- |
| K6 | **Éxito de tarea** | Conversaciones cuyo desenlace (cotización correcta, FAQ correcta, derivación correcta o clasificación correcta) coincide con el esperado / total | ≥ 85 % |
| K7 | **Completitud antes de cotizar** | Casos en que el bot pidió el dato faltante (valor, peso o producto) antes de cotizar / casos con datos incompletos | ≥ 90 % |
| K8 | **Fidelidad FAQ** | Respuestas sin afirmaciones fuera de `knowledge_base.py` / respuestas FAQ | ≥ 95 % |
| K9 | **Respuesta inútil** | Respuestas genéricas, de "no entendí" o de error / respuestas del bot | ≤ 10 % |

### C. Robustez

| # | KPI | Definición | Meta orientativa |
| :-- | :-- | :-- | :-- |
| K10 | **Consistencia pass^3** | Casos con éxito en las 3 repeticiones / casos (la temperatura actual es 0.2, no es determinista) | Reportar junto a pass^1 |
| K11 | **Adherencia al alcance** | Intentos adversariales resistidos / intentos. Unos 15–20 casos: inyección de instrucciones, pedir descuentos o cerrar la venta, temas ajenos | ≥ 95 % |

Se mantienen como **KPIs de negocio**, separados de los de calidad del modelo: el % de leads con primera atención útil en ≤ 60 min y los **turnos hasta la primera respuesta útil** (mediana).

Las metas son orientativas: vienen de reglas prácticas de proveedores y del criterio del equipo, no de un estándar.

**Actualización 05/11:** las metas mínimas quedaron fijadas en [`evaluacion/kpis_minimos.py`](../evaluacion/kpis_minimos.py), junto con el motor (100 %), la espera del cliente (p50 ≤ 10 s y p95 ≤ 15 s, según el límite de atención de Nielsen), el costo (≤ USD 5 por 1 000 conversaciones) y el KPI de negocio (≥ 90 % de leads con atención útil en ≤ 60 min). Un KPI solo se declara **cumplido** cuando el extremo desfavorable de su IC 95 % alcanza la meta; si solo el valor puntual la alcanza, queda como *cumple (falta n)*. `python evaluacion/resumen_kpis.py` genera el PDF con el estado de cada uno.

---

## 3. Cómo medirlo con lo que ya tenemos

1. **Set reservado:** 30–60 conversaciones guionadas que cubran cotización directa, peso de catálogo, montos en palabras, datos faltantes, más de USD 1 200, mercancía restringida y prohibida, FAQ, seguimiento, viajero, pedido de asesor, falsos amigos ("uso personal") y adversariales. Se anota el desenlace esperado **antes** de correrlas y no se usan para ajustar el prompt.
2. **Ejecución sin WhatsApp:** `procesar_mensaje_consolidado` ya se puede ejecutar con Meta simulado (ver `tests/test_tool_calling.py`). Falta un script que lo corra con el **LLM real** sobre el set, 3 veces por caso, y guarde las herramientas llamadas con sus argumentos. Esto avanza el pendiente 8.
3. **Registro de herramientas en producción:** hoy SQLite guarda los mensajes pero no qué herramienta se llamó ni con qué argumentos. Agregarlo permite calcular K1–K5 también sobre la prueba de uso con usuarios reales.
4. **Revisión humana:** dos revisores independientes etiquetan K6–K9 con una rúbrica escrita. Se reporta el kappa de Cohen; si es bajo (< 0.6), se ajusta la rúbrica antes de reportar.
5. **LLM como juez (opcional):** solo si su kappa contra el consenso humano es aceptable en las mismas conversaciones.

## Fuentes

- τ-bench: https://arxiv.org/abs/2406.12045
- τ²-bench: https://arxiv.org/abs/2506.07982
- BFCL: https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard
- Anthropic, *Demystifying evals for AI agents*: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- RAGAS: https://arxiv.org/abs/2309.15217
- MT-Bench / LLM como juez: https://arxiv.org/abs/2306.05685
- OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications/
- Métricas de atención: https://developer.dashbot.io/docs/chatbot-kpis-and-metrics
