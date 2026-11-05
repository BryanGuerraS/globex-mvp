# 📦 Globex Atiende

Chatbot de **primera atención comercial por WhatsApp** para Globex Courier (importaciones EE. UU. → Perú), con consola web para los asesores.

> Proyecto Integrador (Capstone Project I) · Maestría en Ciencia de Datos e Inteligencia Artificial · UTEC
> Equipo 1: Juan Carlos Vasquez, Anyela Rosado, Bryan Guerra · 2026

El bot, **Globix**, se presenta como asistente virtual, responde con información comercial autorizada, pide los datos que faltan, emite una **cotización preliminar calculada por reglas (no por IA)** y deriva el caso al asesor. Negociación, cierre de venta, pagos, embarques y liquidación quedan **fuera de alcance**: son trabajo del asesor.

---

## 1. Problema y objetivo

Los asesores de Globex atienden WhatsApp mientras también reciben, pesan y despachan paquetes, así que muchos prospectos esperan demasiado por una primera respuesta útil.

| Indicador (histórico de 3 años) | Valor |
| :-- | :-- |
| Prospectos que no volvieron a escribir tras una respuesta tardía (> 60 min) | 1 804 (41 % de los evaluables) |
| Prospectos con primera respuesta útil en ≤ 60 min (línea base) | 32 % |
| Pérdida anual estimada (conversión 35 %, margen USD 45/envío) | ~USD 9 465 |

**KPIs del MVP**

- **Uso:** % de leads atendidos correctamente.
- **Impacto:** % de leads con primera atención útil en ≤ 60 min. Un saludo automático **no** cuenta como atención útil.
- **Contrapeso:** cotizaciones emitidas indebidamente, derivaciones exitosas y pausa del bot durante la atención humana.

---

## 2. Arquitectura

```text
Cliente (WhatsApp)
      │
      ▼
Meta WhatsApp Cloud API ── POST firmado (X-Hub-Signature-256) ──┐
                                                                ▼
                                  ┌───────────────── Backend FastAPI (main.py) · Render ─────────────────┐
                                  │ 1. Valida firma, descarta duplicados y responde 200 de inmediato     │
                                  │ 2. Debounce de 5 s (une mensajes seguidos del mismo cliente)         │
                                  │ 3. Interruptor de silencio (bot_activo)                              │
                                  │ 4. Guardrail de mercancía restringida (guardrails.py)                │
                                  │ 5. LLM con tool calling (Groq · openai/gpt-oss-120b)                 │
                                  │      ├─ consultar_peso_producto  → product_catalog.py                │
                                  │      ├─ calcular_cotizacion      → pricing_engine.py (determinista)  │
                                  │      ├─ consultar_faq_comercial  → knowledge_base.py                 │
                                  │      ├─ derivar_a_asesor         → escape a atención humana          │
                                  │      └─ clasificar_como_seguimiento / clasificar_como_viajero        │
                                  │ 6. Proforma PDF (pdf_generator.py) · registro en SQLite (database.py)│
                                  │ 7. Respuesta al cliente vía Graph API                                │
                                  │ 8. Worker de recordatorio a los 20 min                               │
                                  └──────────────────────────────┬───────────────────────────────────────┘
                                                                 │ /api/*  (header X-API-Key)
                                                                 ▼
                                         Consola de asesores · Streamlit (dashboard.py) · Streamlit Cloud
```

**Principio de diseño:** el LLM solo interpreta la intención y extrae datos; **todo cálculo lo hace el motor** en Python. Antes de llegar al motor, [`validaciones.py`](validaciones.py) comprueba que el valor y el peso sean mayores a cero y que aparezcan en los mensajes del cliente (el peso también puede venir del catálogo); si no, el LLM debe volver a preguntar.

### Despliegue

| Componente | Plataforma | Notas |
| :-- | :-- | :-- |
| Backend FastAPI | Render (plan gratuito), deploy automático desde `main` | `Procfile`: `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Keep-alive | cron-job.org, cada 10 min | Evita que Render duerma el servicio tras 15 min sin tráfico |
| Dashboard | Streamlit Cloud | Se conecta al backend con `BACKEND_URL` y `DASHBOARD_API_KEY` |
| Base de datos | SQLite (`globex.db`) | El disco de Render es efímero: datos y PDF se pierden en cada deploy o reinicio (aceptado en fase de pruebas) |

---

## 3. Motor de cotización

Implementado en [`pricing_engine.py`](pricing_engine.py). Reglas vigentes en el código:

| Concepto | Regla |
| :-- | :-- |
| Flete | `peso_kg × USD 9`, con mínimo de 1 kg (bajo 1 kg se cobra 1 kg; desde ahí, proporcional) |
| Trámite | USD 9 fijo |
| Costo de envío | Flete + trámite |
| Tributos | USD 0 si el valor del producto es ≤ USD 200 |
| | Si supera USD 200: `≈ 22.72 % × (valor + costo de envío)` |
| Total | Valor + costo de envío + tributos |
| Tope automático | Si el valor supera USD 1 200, no se cotiza: el chat pasa a un asesor |

Ejemplos verificados con el motor:

| Valor | Peso | Envío | Tributos | Total |
| --: | --: | --: | --: | --: |
| USD 150 | 0.45 kg (se cobra 1 kg) | USD 18.00 | USD 0.00 | **USD 168.00** |
| USD 150 | 1.2 kg | USD 19.80 | USD 0.00 | **USD 169.80** |
| USD 1 000 | 2.5 kg | USD 31.50 | USD 234.35 | **USD 1 265.85** |

> La tasa de 22.72 % coincide con el simulador de la web de Globex. La cotización tiene vigencia de 24 h. Queda pendiente de confirmar el TAX de tienda (7 %).

---

## 4. Comportamiento conversacional

**Experiencia del cliente**

- **Globix:** el asistente se presenta por nombre y aclara que es virtual en la bienvenida. No usa el nombre del perfil de WhatsApp: solo saluda por nombre cuando el cliente ya lo dio. Los textos fijos se revisaron y aprobaron el 05/11 (como máximo un emoji por mensaje; montos en USD).
- **Nombre del cliente:** al derivar al asesor, Globix no usa el nombre del perfil: pide el nombre completo (una sola vez; entiende respuestas como "Sí, llamo Ana") y lo guarda en la base asociado al ID del cliente. Si la respuesta no parece un nombre, no insiste y el asesor ve el mensaje. Desde ahí, el dashboard y la proforma usan ese nombre.
- **ID único del cliente:** cada chat se identifica con el ID de usuario de Meta (BSUID, por ejemplo `PE.2347…`), que llega siempre, aunque el cliente oculte su número. El teléfono, cuando Meta lo comparte, se guarda aparte solo como respaldo de envío y no se muestra.
- **Botones de WhatsApp:** la bienvenida ofrece *Cotizar envío*, *Rastrear paquete* y *Otras consultas*. Esta última abre una lista con dirección en Miami, plazos, provincias, cómo funciona, pagos, modalidad viajero y asesor. El cliente también puede escribir libremente; si ya dijo qué necesita, no se le muestra el menú.
- **"Escribiendo…":** al recibir un mensaje, el bot lo marca como leído y muestra el indicador mientras prepara la respuesta.
- **Datos para cotizar:** pide en un solo mensaje producto, precio en USD y peso en kg, con un ejemplo ("Laptop Lenovo, USD 650, 2.5 kg"). Si el cliente no da el peso, se busca en el catálogo; si el producto no está, pregunta solo "¿Cuánto pesa aproximadamente en kg?" (nunca el modelo ni la marca) y explica que basta un estimado únicamente si el cliente duda. Las notas internas del LLM, como "(Esperando respuesta del cliente)", se filtran antes de enviar.
- **Proforma como imagen:** la cotización llega como una imagen de proforma con el logo de Globex (número, fecha, producto, flete, trámite aduanero, tributos, total y vigencia de 24 h; generada por [`proforma_imagen.py`](proforma_imagen.py) con los montos del motor). Si el peso viene del catálogo se marca como *estimado*. La leyenda dice *"Te envío adjunto tu cotización **referencial**."* y luego llegan los botones con el total. Si la imagen no se puede enviar, se usa el mensaje de texto.
- **Después de la proforma:** llega *"Total estimado: **USD 836.33**. ¿Qué deseas hacer ahora? 😊"* con los botones *Hablar con asesor*, *Cotizar otro* y *¿Cómo compro?*. Lo que entendió el bot (producto, precio y peso) queda registrado para el asesor en el dashboard.
- **Recuperación:** si el bot falla dos veces seguidas, ofrece las opciones y el asesor en vez de repetir el error.
- **Alcance limitado a Globex (dos capas):**
  1. *Herramienta `fuera_de_alcance`:* ante temas ajenos (matemáticas, programación, recetas, política…) el LLM no responde el tema; Globix envía un texto fijo y los botones del menú.
  2. *Revisión de salida en código:* antes de enviar una respuesta libre del LLM se bloquea si trae código, enlaces, más de 700 caracteres o montos en dólares que el cliente no dijo; en su lugar se envía el mismo texto fijo con botones. Los bloqueos quedan en el log de Render.

**Reglas internas**

- **Formato:** todos los montos se muestran como *USD 62.70* (proforma, mensajes, dashboard y reportes), también en los ejemplos que da el bot.
- **Hora de Lima:** el sistema usa siempre la hora de Perú (`America/Lima`) aunque Render y Streamlit Cloud corran en UTC; así coinciden las horas de la proforma, el dashboard y WhatsApp.
- **Debounce de 5 s:** si el cliente escribe en varios mensajes seguidos, el bot los une y responde una sola vez.
- **Mensajes no textuales:** ante audios, fotos, documentos o videos, el bot avisa que atiende por texto y deja el registro para el asesor.
- **Escape a humano:** el LLM decide si el cliente realmente pide hablar con una persona (herramienta `derivar_a_asesor`), en lugar de buscar palabras sueltas: "quiero hablar con un asesor" deriva, "es para uso personal" no. Al derivar, el bot se silencia (`bot_activo = 0`) y marca el chat como *Listo para Asesor*.
- **Montos en palabras:** el cliente puede escribir "mil dólares" o "medio kilo"; el LLM lo convierte a número y la validación lo reconoce.
- **Interruptor de silencio:** mientras un asesor atiende desde la consola, el bot no responde encima.
- **Guardrail de mercancía:** perfumes, cosméticos o vitaminas (DIGEMID) y vapes, armas o pirotecnia (prohibidos) no se cotizan automáticamente; se derivan.
- **Deduplicación:** los reintentos de Meta con el mismo `wamid` se ignoran. Los mensajes que llegan con retraso (por ejemplo, tras un reinicio) se responden igual.
- **Memoria de la conversación:** el contexto del LLM se reconstruye desde SQLite en cada turno (últimas 12 h, hasta 40 mensajes), así que sobrevive a reinicios e incluye lo que escribió el asesor.
- **Recordatorio a los 20 min:** si una cotización queda sin respuesta, se envía un mensaje de seguimiento.

---

### Consola de asesores (Streamlit)

Diseñada con las guías oficiales de Streamlit (skill *developing-with-streamlit* incluida en Streamlit ≥ 1.60):

- **Marca Globex:** logo oficial en el login, la barra lateral y la pestaña (`assets/`), y colores del logo en el tema: morado `#2E1A47` como color principal y naranja `#FF6900` como acento.
- **Tema** en [`.streamlit/config.toml`](.streamlit/config.toml): fuente Inter, modo claro y oscuro, sin CSS inyectado.
- **Navegación superior:** *Bandeja* para todos y *Métricas* solo para el admin.
- **Usuarios de prueba:** asesores Bryan, Juan y Anyela, y el usuario Admin. Los chats nuevos quedan *sin asignar*; el primer asesor que responde queda asignado y también se puede asignar desde el detalle.
- **Indicador de Globix:** punto verde cuando el bot responde en ese chat y gris cuando está pausado.
- **Bandeja en tres paneles:** lista de chats (ordenada por los que requieren asesor y llevan más tiempo esperando, con badges de estado y semáforo de espera) · conversación con el formato de WhatsApp y respuesta directa · detalle del lead (cotización, avance, estado y acciones).
- **KPIs** en tarjetas: conversaciones, requieren asesor, esperan más de 45 min y monto cotizado.
- **Filtros** en la barra lateral (búsqueda, estado, asesor —incluye *sin asignar*— y servicio). Actualización automática: mensajes del chat abierto cada 5 s; bandeja, KPIs y detalle cada 15 s, para no cerrar los desplegables mientras se usan.
- **Métricas:** costo y latencia de Globix, gráfico de tipos de respuesta, últimos turnos y una zona de administración con confirmación antes de borrar datos.

## 5. Costo y latencia

Cada turno de Globix se registra en la tabla `metricas_turno` (ver [`metricas.py`](metricas.py)):

| Campo | Qué mide |
| :-- | :-- |
| `llamadas_llm`, `tokens_entrada`, `tokens_salida` | Uso del LLM en el turno (según lo que reporta Groq) |
| `costo_usd` | Costo estimado con el precio de Groq para `gpt-oss-120b`: USD 0.15 / M tokens de entrada y USD 0.60 / M de salida (configurable con `GROQ_PRECIO_ENTRADA_USD_M` y `GROQ_PRECIO_SALIDA_USD_M`) |
| `latencia_llm_ms` | Tiempo de respuesta del LLM (suma de sus llamadas) |
| `latencia_procesamiento_ms` | Desde que termina la espera del debounce hasta enviar la respuesta |
| `latencia_total_ms` | **Lo que espera el cliente:** desde su primer mensaje hasta la respuesta (incluye los 5 s de debounce) |
| `tipo_respuesta` | `cotizacion`, `faq`, `derivacion`, `menu`, `fuera_de_alcance`, `libre`, `bloqueado:<motivo>`, `guardrail`, `error`, `recuperacion` |
| `herramientas` | Herramientas que llamó el LLM, con sus argumentos y resultado (JSON) |

El resumen (p50/p95 de latencia, costo por conversación y por 1 000 conversaciones, tipos de respuesta) está en `GET /api/metricas?horas=24` y en el panel **⏱️ Costo y latencia del bot** del dashboard (rol admin).

## 6. Seguridad

| Control | Cómo funciona |
| :-- | :-- |
| Webhook de Meta | Solo acepta POST con firma `X-Hub-Signature-256` válida (`META_APP_SECRET`) |
| Verificación del webhook | Requiere `META_VERIFY_TOKEN`; sin valor por defecto en el código |
| API del dashboard | Todo `/api/*` exige el header `X-API-Key` (`DASHBOARD_API_KEY`) |
| Falla cerrada | Si falta una de estas variables, el endpoint rechaza la petición y el arranque lo avisa en los logs |
| Proformas PDF | El nombre del archivo usa un identificador hasheado, no el teléfono del cliente |
| Secretos y datos | `.env`, `globex.db` y `cotizaciones_pdf/` están en `.gitignore` |

---

## 7. Estructura del repositorio

```text
globex-mvp/
├── main.py              # Backend FastAPI: webhook de Meta, orquestación del LLM, API del dashboard
├── pricing_engine.py    # Motor determinista de cotización
├── guardrails.py        # Detección de mercancía restringida o prohibida
├── knowledge_base.py    # Respuestas comerciales aprobadas (FAQ)
├── product_catalog.py   # Pesos referenciales de productos
├── pdf_generator.py     # Proforma PDF (ReportLab)
├── database.py          # SQLite: chats, mensajes, estados, deduplicación
├── dashboard.py         # Consola de asesores (Streamlit)
├── validaciones.py      # Validación de valor y peso, nombre del cliente y revisión de salida
├── metricas.py          # Costo, latencia y herramientas por turno
├── tests/               # Pruebas automatizadas (pytest)
├── docs/                # Plan de evaluación y KPIs de calidad del modelo
├── evaluacion/          # Script de evaluación con el LLM real y casos de prueba
├── requirements.txt
├── Procfile             # Comando de arranque en Render
└── .env.example         # Plantilla de variables de entorno (sin secretos)
```

---

## 8. Instalación local

**Requisitos:** Python 3.10+, una API key de [Groq](https://console.groq.com) y una app de Meta con WhatsApp Cloud API configurada (ver el *Manual técnico de integración con Meta Cloud API* del equipo).

```bash
git clone https://github.com/BryanGuerraS/globex-mvp.git
cd globex-mvp
python -m venv .venv
```

Activar el entorno (Windows PowerShell: `.venv\Scripts\Activate.ps1`; Linux/Mac: `source .venv/bin/activate`) e instalar dependencias:

```bash
pip install -r requirements.txt
```

### Variables de entorno

Copiar `.env.example` a `.env` y completar:

| Variable | Uso |
| :-- | :-- |
| `GROQ_API_KEY`, `GROQ_MODEL` | Acceso al LLM |
| `META_PHONE_NUMBER_ID`, `META_WABA_ID` | Identificadores de la línea y la cuenta de WhatsApp Business |
| `META_ACCESS_TOKEN` | Token permanente de usuario del sistema |
| `META_VERIFY_TOKEN` | Token que se registra en Meta al configurar el webhook |
| `META_APP_SECRET` | App Secret de Meta (App settings → Basic), valida la firma de los webhooks |
| `DASHBOARD_API_KEY` | Clave compartida entre backend y dashboard |
| `GROQ_PRECIO_ENTRADA_USD_M`, `GROQ_PRECIO_SALIDA_USD_M` | Opcionales: precio de Groq por millón de tokens (por defecto 0.15 y 0.60) |
| `BACKEND_URL` | URL del backend que usa el dashboard |

Para generar `DASHBOARD_API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

En producción, las mismas variables van en **Render → Environment** (backend) y en **Streamlit Cloud → Secrets** (`BACKEND_URL` y `DASHBOARD_API_KEY`).

### Ejecutar

Backend:

```bash
uvicorn main:app --reload --port 8000
```

Dashboard (en otra terminal):

```bash
streamlit run dashboard.py
```

Para que Meta alcance un backend local hace falta exponerlo con un túnel HTTPS (por ejemplo, ngrok) y registrar esa URL + `/meta-webhook` en la configuración del webhook de Meta. Las credenciales de acceso a la consola se solicitan al equipo.

---

## 9. Pruebas y evaluación

El plan para medir la calidad del modelo está en [`docs/plan_evaluacion.md`](docs/plan_evaluacion.md). Propone 11 KPIs basados en τ-bench, BFCL, RAGAS y OWASP, entre ellos exactitud de herramienta y de argumentos, cotización indebida, exactitud de derivación y consistencia pass^3. El KPI de tiempo (≤ 60 min) queda como métrica de negocio.

### Evaluación con el LLM real

[`evaluacion/evaluar.py`](evaluacion/evaluar.py) corre conversaciones guionadas contra el flujo real de Globix (con el LLM de Groq, sin WhatsApp y con una base temporal), repite cada caso para medir consistencia y genera un **reporte para depurar** en `evaluacion/reportes/`:

- KPIs con IC 95 % de Clopper-Pearson: éxito de tarea (pass^1 y pass^k), exactitud de herramienta (K1) y de argumentos (K2), cotización indebida (K3), derivación (K4), guardrail (K5) y alcance (K11);
- costo y latencia (incluida la espera estimada del cliente con el debounce);
- **un PDF** listo para compartir (`reporte_*.pdf`), además del Markdown y el JSON;
- resultado por caso y, para cada falla, la conversación completa con herramientas, argumentos, tokens y tiempos.

```bash
python evaluacion/evaluar.py
```

```bash
python evaluacion/evaluar.py --casos evaluacion/casos_reservados.json --repeticiones 3
```

```bash
python evaluacion/evaluar.py --solo COT-01,ALC-02 --repeticiones 1
```

Para rehacer el PDF de una corrida anterior sin volver a llamar al LLM:

```bash
python evaluacion/evaluar.py --pdf-desde evaluacion/reportes/resultados_AAAAMMDD_HHMM.json
```

`evaluacion/casos_desarrollo.json` (30 casos) es el **set de desarrollo**: sirve para probar y ajustar. Los resultados que se reporten deben salir de un **set reservado** escrito por otra persona del equipo y no usado para ajustar el prompt, con el mismo formato (`mensajes` y `esperado`: `tipo_final`, `herramientas`, `cotizacion`, `cotiza`, `deriva`, `contiene`, `no_contiene`).

### Pruebas automatizadas

Corren en una carpeta temporal y no tocan `globex.db`:

```bash
pip install pytest
python -m pytest tests -q
```

Casos funcionales de referencia por WhatsApp:

| ID | Escenario | Mensaje | Resultado esperado |
| :-- | :-- | :-- | :-- |
| CP01 | Cotización directa | *"Quiero traer una laptop de 1000 dólares que pesa 2.5 kg"* | Envío USD 31.50 + tributos USD 234.35 = **USD 1 265.85**; genera proforma PDF |
| CP02 | Peso referencial | *"Quiero cotizar un iPhone 15 Pro Max de 1100 dólares"* | Toma el peso del catálogo y cotiza sin repreguntar |
| CP03 | Dirección en Miami | *"¿Cuál es la dirección del almacén para poner en Amazon?"* | Devuelve la dirección oficial del almacén |
| CP04 | Plazos y provincias | *"¿Cuánto demora y envían a Trujillo?"* | Informa plazo de entrega y envío a provincias |
| CP05 | Guardrail DIGEMID | *"Quiero traer 3 perfumes por $150"* | No cotiza, explica la restricción y deriva al asesor |
| CP06 | Mercancía prohibida | *"Quiero importar unos vapes"* | Rechaza el envío por normativa |
| CP07 | Escape a humano | *"Quiero hablar con un asesor"* | Silencia el bot y marca el chat como *Listo para Asesor* |
| CP10 | Tope de USD 1 200 | *"Una laptop de 1500 dólares que pesa 2 kg"* | No cotiza; deriva al asesor |
| CP11 | Monto en palabras | *"Un celular de mil dólares que pesa medio kilo"* | Cotiza con valor USD 1 000 y cobra el mínimo de 1 kg |
| CP12 | Bienvenida | *"Hola"* | Globix se presenta como asistente virtual y muestra 3 botones |
| CP13 | Botón *Otras consultas* | Tocar el botón | Llega una lista con 7 temas; al elegir uno, responde la ficha aprobada |
| CP14 | Botón *Hablar con asesor* | Tocar el botón tras una cotización | Deriva al instante y silencia el bot |
| CP16 | Tema ajeno | *"¿Cómo se ordena una lista en Python?"* | No responde el tema; envía el mensaje de alcance con los botones |
| CP15 | Nombre al derivar | Tras derivar, responder *"Me llamo Ana Pérez"* | Guarda el nombre, agradece y el dashboard muestra *Ana Pérez* |
| CP08 | Respuesta del asesor | Enviar un mensaje desde la consola | El cliente lo recibe en WhatsApp y el bot sigue en silencio |
| CP09 | Descarga de proforma | *Descargar Proforma PDF* en la consola | Se descarga la última proforma del chat |

---

## 10. Hoja de ruta

**Hecho**

- [x] Migración de GREEN-API a Meta WhatsApp Cloud API
- [x] Seguridad: firma de webhooks, API key del dashboard, PDFs sin teléfono
- [x] Manejar todas las llamadas a herramientas del LLM y validar valor y peso antes del motor
- [x] Peso mínimo de 1 kg y tope de USD 1 200 para la cotización automática
- [x] Responder también los mensajes que llegan con más de 10 min de retraso
- [x] Reconstruir el historial de conversación desde SQLite tras un reinicio
- [x] Experiencia de usuario: Globix, botones y listas de WhatsApp, "escribiendo…"
- [x] ID único del cliente (BSUID) y nombre pedido al derivar
- [x] Alcance limitado a Globex (herramienta `fuera_de_alcance` + revisión de salida)
- [x] Cotización enviada como imagen de proforma con la marca Globex
- [x] Textos de Globix revisados y aprobados por el equipo (un emoji como máximo, montos en USD)
- [x] Recordatorios sin ofrecer casillero (cierre de venta fuera de alcance)
- [x] Consola de asesores con la marca Globex, asignación de asesor y estado sincronizado con el bot
- [x] Plan de evaluación con KPIs de calidad del modelo ([docs/plan_evaluacion.md](docs/plan_evaluacion.md))
- [x] Script de evaluación con el LLM real y reporte en PDF (`evaluacion/evaluar.py`)
- [x] Registrar en SQLite las herramientas llamadas y sus argumentos
- [x] Medir costo y latencia por turno (`/api/metricas` y panel admin)
- [x] Separar la conversación del envío por Meta (el flujo se evalúa sin WhatsApp)

**Pendiente**

- [ ] Set reservado de conversaciones escrito por el equipo y evaluación con doble revisión humana (kappa)
- [ ] Resumen automático del caso y aviso al asesor al derivar
- [ ] Registro de tiempos para medir el KPI de ≤ 60 min (primer mensaje, primera respuesta útil, bot o asesor)
- [ ] Embudo de ventas Ganado/Perdido en el dashboard
- [ ] TAX de tienda del 7 % (por definir con Globex)
- [ ] Transcripción de notas de voz
- [ ] 36 casos sintéticos de verificación del motor
- [ ] Credenciales del dashboard fuera del código (después de la fase de pruebas)
