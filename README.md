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

- **Globix:** el asistente se presenta por nombre y aclara que es virtual en la bienvenida. Saluda con el nombre del perfil de WhatsApp si parece un nombre real.
- **Nombre del cliente:** al derivar al asesor, Globix pide el nombre completo (una sola vez) y lo guarda en la base asociado al ID del cliente. Si la respuesta no parece un nombre, no insiste y el asesor ve el mensaje. Desde ahí, el dashboard y la proforma usan ese nombre.
- **ID único del cliente:** cada chat se identifica con el ID de usuario de Meta (BSUID, por ejemplo `PE.2347…`), que llega siempre, aunque el cliente oculte su número. El teléfono, cuando Meta lo comparte, se guarda aparte solo como respaldo de envío y no se muestra.
- **Botones de WhatsApp:** la bienvenida ofrece *Cotizar envío*, *Rastrear paquete* y *Otras consultas*. Esta última abre una lista con dirección en Miami, plazos, provincias, cómo funciona, pagos, modalidad viajero y asesor. El cliente también puede escribir libremente; si ya dijo qué necesita, no se le muestra el menú.
- **"Escribiendo…":** al recibir un mensaje, el bot lo marca como leído y muestra el indicador mientras prepara la respuesta.
- **Un dato a la vez:** para cotizar pide primero producto y precio, luego el peso (o el modelo para estimarlo), siempre con un ejemplo.
- **Confirmación:** la cotización empieza con lo que entendió el bot, por ejemplo *"Entendí: laptop Lenovo, USD 650, 2.5 kg"*, y termina con los botones *Hablar con asesor*, *Cotizar otro* y *¿Cómo compro?*.
- **Recuperación:** si el bot falla dos veces seguidas, ofrece las opciones y el asesor en vez de repetir el error.

**Reglas internas**

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

## 5. Seguridad

| Control | Cómo funciona |
| :-- | :-- |
| Webhook de Meta | Solo acepta POST con firma `X-Hub-Signature-256` válida (`META_APP_SECRET`) |
| Verificación del webhook | Requiere `META_VERIFY_TOKEN`; sin valor por defecto en el código |
| API del dashboard | Todo `/api/*` exige el header `X-API-Key` (`DASHBOARD_API_KEY`) |
| Falla cerrada | Si falta una de estas variables, el endpoint rechaza la petición y el arranque lo avisa en los logs |
| Proformas PDF | El nombre del archivo usa un identificador hasheado, no el teléfono del cliente |
| Secretos y datos | `.env`, `globex.db` y `cotizaciones_pdf/` están en `.gitignore` |

---

## 6. Estructura del repositorio

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
├── validaciones.py      # Validación de valor y peso antes del motor (dígitos o palabras)
├── tests/               # Pruebas automatizadas (pytest)
├── docs/                # Plan de evaluación y KPIs de calidad del modelo
├── requirements.txt
├── Procfile             # Comando de arranque en Render
└── .env.example         # Plantilla de variables de entorno (sin secretos)
```

---

## 7. Instalación local

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

## 8. Pruebas y evaluación

El plan para medir la calidad del modelo está en [`docs/plan_evaluacion.md`](docs/plan_evaluacion.md). Propone 11 KPIs basados en τ-bench, BFCL, RAGAS y OWASP, entre ellos exactitud de herramienta y de argumentos, cotización indebida, exactitud de derivación y consistencia pass^3. El KPI de tiempo (≤ 60 min) queda como métrica de negocio.

Pruebas automatizadas (corren en una carpeta temporal y no tocan `globex.db`):

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
| CP15 | Nombre al derivar | Tras derivar, responder *"Me llamo Ana Pérez"* | Guarda el nombre, agradece y el dashboard muestra *Ana Pérez* |
| CP08 | Respuesta del asesor | Enviar un mensaje desde la consola | El cliente lo recibe en WhatsApp y el bot sigue en silencio |
| CP09 | Descarga de proforma | *Descargar Proforma PDF* en la consola | Se descarga la última proforma del chat |

---

## 9. Hoja de ruta

- [x] Migración de GREEN-API a Meta WhatsApp Cloud API
- [x] Seguridad: firma de webhooks, API key del dashboard, PDFs sin teléfono
- [x] Manejar todas las llamadas a herramientas del LLM y validar valor y peso antes del motor
- [x] Peso mínimo de 1 kg y tope de USD 1 200 para la cotización automática
- [x] Responder también los mensajes que llegan con más de 10 min de retraso
- [x] Reconstruir el historial de conversación desde SQLite tras un reinicio
- [x] Experiencia de usuario: Globix, botones y listas de WhatsApp, "escribiendo…", confirmación de datos
- [ ] Resumen automático del caso al derivar al asesor
- [x] Plan de evaluación con KPIs de calidad del modelo ([docs/plan_evaluacion.md](docs/plan_evaluacion.md))
- [ ] Script de evaluación con el LLM real sobre un set reservado (3 repeticiones por caso)
- [ ] Registrar en SQLite las herramientas llamadas y sus argumentos
- [ ] Registro de tiempos para medir el KPI de ≤ 60 min
- [ ] 36 casos sintéticos de verificación del motor
- [ ] Credenciales del dashboard fuera del código (después de la fase de pruebas)
