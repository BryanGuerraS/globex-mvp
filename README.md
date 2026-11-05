# 📦 Globex Atiende

Chatbot de **primera atención comercial por WhatsApp** para Globex Courier (importaciones EE. UU. → Perú), con consola web para los asesores.

> Proyecto Integrador (Capstone Project I) · Maestría en Ciencia de Datos e Inteligencia Artificial · UTEC
> Equipo 1: Juan Carlos Vasquez, Anyela Rosado, Bryan Guerra · 2026

El bot responde con información comercial autorizada, pide los datos que faltan, emite una **cotización preliminar calculada por reglas (no por IA)** y deriva el caso al asesor. Negociación, cierre de venta, pagos, embarques y liquidación quedan **fuera de alcance**: son trabajo del asesor.

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
                                  │ 3. Escape a humano · interruptor de silencio (bot_activo)            │
                                  │ 4. Guardrail de mercancía restringida (guardrails.py)                │
                                  │ 5. LLM con tool calling (Groq · openai/gpt-oss-120b)                 │
                                  │      ├─ consultar_peso_producto  → product_catalog.py                │
                                  │      ├─ calcular_cotizacion      → pricing_engine.py (determinista)  │
                                  │      ├─ consultar_faq_comercial  → knowledge_base.py                 │
                                  │      └─ clasificar_como_seguimiento / clasificar_como_viajero        │
                                  │ 6. Proforma PDF (pdf_generator.py) · registro en SQLite (database.py)│
                                  │ 7. Respuesta al cliente vía Graph API                                │
                                  │ 8. Worker de recordatorio a los 20 min                               │
                                  └──────────────────────────────┬───────────────────────────────────────┘
                                                                 │ /api/*  (header X-API-Key)
                                                                 ▼
                                         Consola de asesores · Streamlit (dashboard.py) · Streamlit Cloud
```

**Principio de diseño:** el LLM solo interpreta la intención y extrae datos; **todo cálculo lo hace el motor** en Python.

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
| Flete | `peso_kg × USD 9` |
| Trámite | USD 9 fijo |
| Costo de envío | Flete + trámite |
| Tributos | USD 0 si el valor del producto es ≤ USD 200 |
| | Si supera USD 200: `≈ 22.72 % × (valor + costo de envío)` |
| Total | Valor + costo de envío + tributos |

Ejemplos verificados con el motor:

| Valor | Peso | Envío | Tributos | Total |
| --: | --: | --: | --: | --: |
| USD 150 | 1.2 kg | USD 19.80 | USD 0.00 | **USD 169.80** |
| USD 1 000 | 2.5 kg | USD 31.50 | USD 234.35 | **USD 1 265.85** |

> ⚠️ **Reglas en revisión con Globex.** Están pendientes de confirmar el peso mínimo de 1 kg, el tope de USD 1 200 para el cálculo automático, el TAX de tienda (7 %), la tasa de tributos y la vigencia de la cotización. No se cambian sin la confirmación de Globex.

---

## 4. Comportamiento conversacional

- **Debounce de 5 s:** si el cliente escribe en varios mensajes seguidos, el bot los une y responde una sola vez.
- **Mensajes no textuales:** ante audios, fotos, documentos o videos, el bot avisa que atiende por texto y deja el registro para el asesor.
- **Escape a humano:** si el cliente pide un asesor, el bot se silencia (`bot_activo = 0`), marca el chat como *Listo para Asesor* y deja de responder.
- **Interruptor de silencio:** mientras un asesor atiende desde la consola, el bot no responde encima.
- **Guardrail de mercancía:** perfumes, cosméticos o vitaminas (DIGEMID) y vapes, armas o pirotecnia (prohibidos) no se cotizan automáticamente; se derivan.
- **Deduplicación:** los reintentos de Meta con el mismo `wamid` se ignoran.
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
├── tests/               # Pruebas automatizadas (pytest)
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

## 8. Pruebas

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
| CP08 | Respuesta del asesor | Enviar un mensaje desde la consola | El cliente lo recibe en WhatsApp y el bot sigue en silencio |
| CP09 | Descarga de proforma | *Descargar Proforma PDF* en la consola | Se descarga la última proforma del chat |

---

## 9. Hoja de ruta

- [x] Migración de GREEN-API a Meta WhatsApp Cloud API
- [x] Seguridad: firma de webhooks, API key del dashboard, PDFs sin teléfono
- [ ] Manejar todas las llamadas a herramientas del LLM y validar valor y peso antes del motor
- [ ] Responder también los mensajes que llegan con más de 10 min de retraso
- [ ] Reconstruir el historial de conversación desde SQLite tras un reinicio
- [ ] Resumen automático del caso al derivar al asesor
- [ ] Registro de tiempos para medir el KPI de ≤ 60 min
- [ ] 36 casos sintéticos de verificación del motor y evaluación conversacional del LLM
- [ ] Credenciales del dashboard fuera del código
