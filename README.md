# 📦 Globex Atiende

Chatbot de **primera atención comercial por WhatsApp** para Globex Courier (importaciones EE. UU. → Perú), con consola web para los asesores.

> Proyecto Integrador (Capstone Project I) · Maestría en Ciencia de Datos e Inteligencia Artificial · UTEC
> Equipo 1: Juan Carlos Vasquez, Anyela Rosado, Bryan Guerra · 2026

El asistente, **Globix**, responde con información comercial aprobada por Globex, recopila los datos del pedido, emite una **cotización preliminar calculada por reglas (no por IA)** y deriva el caso al asesor con un resumen listo para continuar. Negociación, cierre de venta, verificación de pagos, embarques y liquidación quedan **fuera de alcance**: son trabajo del asesor.

---

## Contenido

1. [Problema y objetivo](#1-problema-y-objetivo)
2. [Funcionalidades](#2-funcionalidades)
3. [Resultados](#3-resultados)
4. [Arquitectura](#4-arquitectura)
5. [Motor de cotización](#5-motor-de-cotización)
6. [Comportamiento conversacional](#6-comportamiento-conversacional)
7. [Consola de asesores](#7-consola-de-asesores)
8. [Métricas en operación](#8-métricas-en-operación)
9. [Evaluación](#9-evaluación)
10. [Instalación y ejecución](#10-instalación-y-ejecución)
11. [Seguridad](#11-seguridad)
12. [Estructura del repositorio](#12-estructura-del-repositorio)
13. [Trabajo futuro](#13-trabajo-futuro)

---

## 1. Problema y objetivo

Los asesores de Globex atienden WhatsApp mientras también reciben, pesan y despachan paquetes, así que muchos prospectos esperan demasiado por una primera respuesta útil.

| Indicador (histórico de 3 años) | Valor |
| :-- | :-- |
| Prospectos que no volvieron a escribir tras una respuesta tardía (> 60 min) | 1 804 (41 % de los evaluables) |
| Prospectos con primera respuesta útil en ≤ 60 min (línea base) | 32 % |
| Pérdida anual estimada (conversión 35 %, margen USD 45/envío) | ~USD 9 465 |

**Objetivo:** que cada prospecto reciba una primera atención útil, correcta y dentro de los 60 minutos, y que el asesor reciba el caso con el contexto necesario para cerrarlo. Un saludo automático **no** cuenta como atención útil.

---

## 2. Funcionalidades

| # | Funcionalidad | Qué hace | Indicador y meta |
| :-: | :-- | :-- | :-- |
| 1 | **Atención inicial y preguntas frecuentes** | Responde con una base de 132 respuestas aprobadas por el equipo, enviadas tal cual, sin redactarlas | Calidad de respuesta a preguntas frecuentes ≥ 85 % |
| 2 | **Recopilación de datos y resumen del caso** | Guarda producto, tienda, cantidad, precio, TAX y peso en un borrador del pedido, pide solo lo que falta y arma el resumen para el asesor | Exactitud y completitud de los datos recopilados ≥ 90 % · Calidad del resumen para el asesor ≥ 85 % |
| 3 | **Cotización referencial** | Calcula con un motor determinista (uno o varios productos) y envía la proforma en imagen | Exactitud del total cotizado ≥ 95 % |
| 4 | **Control de mercancía** | Detecta productos prohibidos, no admitidos, con receta, usados o por encima del máximo por categoría, y no los cotiza | Calidad de respuesta sobre productos con condiciones especiales ≥ 85 % y cero cotizaciones emitidas a pedidos bloqueados |
| 5 | **Derivación al asesor** | Deriva cuando corresponde, pausa el bot y deja el caso con su resumen en la consola | Derivación correcta ≥ 80 % |
| 6 | **Consola del asesor** | Bandeja, conversación, resumen del caso, revisión y envío de la proforma formal | Éxito de tareas en la prueba de uso ≥ 80 % |

Transversal: tiempo de respuesta por turno p50 ≤ 10 s y p95 ≤ 15 s.

---

## 3. Resultados

Evaluación con el **banco final de preguntas del equipo** (228 casos: preguntas frecuentes, derivación, productos con condiciones especiales, cotizaciones y conversaciones de varios mensajes), ejecutado **3 veces completas** contra Globix desplegado (684 casos, sin errores de ejecución). Las respuestas abiertas las califica un juez LLM de otra familia que Globix con la rúbrica y los prompts del banco; la derivación y los totales se comparan con los registros del sistema.

| Indicador | Promedio | Mín–máx | Meta | Estado |
| :-- | --: | --: | --: | :-- |
| Calidad de respuesta a preguntas frecuentes | 91.9 % | 91.9–91.9 % | 85 % | ✅ Cumple |
| Derivación correcta | 100 % | 100–100 % | 80 % | ✅ Cumple |
| Calidad de respuesta sobre productos con condiciones especiales | 90.5 % | 88.6–91.4 % | 85 % | ✅ Cumple |
| Exactitud del total cotizado | 99.2 % | 97.5–100 % | 95 % | ✅ Cumple |
| Exactitud y completitud de los datos recopilados | 98.9 % | 98.6–99.0 % | 90 % | ✅ Cumple |
| Calidad del resumen para el asesor | 88.9 % | 86.7–93.3 % | 85 % | ✅ Cumple |

- **Pedidos bloqueados:** 0 cotizaciones emitidas en las 3 corridas.
- **Tiempo de respuesta por turno:** p50 0.61 s y p95 1.04 s (sin los 5 s de agrupación de mensajes de WhatsApp).
- **Motor de cotización:** 60/60 casos correctos al centavo frente a un oráculo independiente.

El procedimiento para reproducir estos resultados está en [Evaluación](#9-evaluación).

---

## 4. Arquitectura

```text
Cliente (WhatsApp)
      │
      ▼
Meta WhatsApp Cloud API ── POST firmado (X-Hub-Signature-256) ──┐
                                                                ▼
                                  ┌───────────────── Backend FastAPI (main.py) · Render ─────────────────┐
                                  │ 1. Valida firma, descarta duplicados y responde 200 de inmediato     │
                                  │ 2. Agrupa 5 s los mensajes seguidos del mismo cliente                │
                                  │ 3. Interruptor de silencio (bot_activo)                              │
                                  │ 4. Control de mercancía y máximos por categoría (guardrails.py)      │
                                  │ 5. LLM con tool calling (Groq · openai/gpt-oss-120b)                 │
                                  │      ├─ registrar_datos_pedido   → borrador del pedido (borrador.py) │
                                  │      ├─ consultar_peso_producto  → product_catalog.py                │
                                  │      ├─ calcular_cotizacion      → pricing_engine.py (determinista)  │
                                  │      ├─ buscar_faq / enviar_faq  → base de 132 respuestas aprobadas  │
                                  │      ├─ consultar_faq_comercial  → knowledge_base.py                 │
                                  │      ├─ consultar_regla_producto → máximos por categoría             │
                                  │      ├─ derivar_a_asesor         → escape a atención humana          │
                                  │      ├─ fuera_de_alcance / mostrar_menu                              │
                                  │      └─ clasificar_como_seguimiento / clasificar_como_viajero        │
                                  │ 6. Proforma en imagen y PDF · registro en SQLite (database.py)       │
                                  │ 7. Respuesta al cliente vía Graph API                                │
                                  │ 8. Recordatorio a los 20 min                                         │
                                  └──────────────────────────────┬───────────────────────────────────────┘
                                                                 │ /api/*  (header X-API-Key)
                                                                 ▼
                                         Consola de asesores · Streamlit (dashboard.py) · Streamlit Cloud
```

**Principio de diseño:** el LLM interpreta la intención y extrae los datos; **todo cálculo lo hace el motor** en Python. Antes de llegar al motor, [`validaciones.py`](validaciones.py) comprueba que cada dato sea válido y aparezca en los mensajes del cliente (el peso también puede venir del catálogo); si no, el LLM vuelve a preguntar.

| Componente | Plataforma | Notas |
| :-- | :-- | :-- |
| Backend FastAPI | Render, despliegue automático desde `main` | `Procfile`: `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Keep-alive | cron-job.org, cada 10 min | Evita que el plan gratuito de Render duerma el servicio |
| Consola de asesores | Streamlit Cloud | Se conecta al backend con `BACKEND_URL` y `DASHBOARD_API_KEY` |
| Base de datos | SQLite (`globex.db`) | En el plan gratuito de Render el disco es efímero: la base y los PDF se reinician con cada despliegue |
| LLM | Groq (`openai/gpt-oss-120b`), keys de respaldo | La evaluación por API usa Cerebras con el mismo modelo |

---

## 5. Motor de cotización

Implementado en [`pricing_engine.py`](pricing_engine.py), con aritmética `Decimal` y redondeo comercial a 2 decimales por línea.

| Concepto | Regla |
| :-- | :-- |
| Flete | `peso_kg × USD 9`, con mínimo de 1 kg (bajo 1 kg se cobra 1 kg; desde ahí, proporcional) |
| Trámite (desaduanaje) | USD 9 fijo, una vez por cotización |
| Costo de envío | Flete + trámite |
| Precio | Precio unitario × cantidad |
| TAX de tienda | El monto que indica el cliente; 0 si dice que el precio ya incluye el TAX o que la tienda no lo cobra; si no lo indica, 7 % del precio |
| Boleta | Suma de precio + TAX de todos los productos (el envío dentro de EE. UU. está fuera de alcance) |
| Tributos | USD 0 si la boleta es menor a USD 200; desde USD 200, `24 % × boleta` |
| Total | Boleta + costo de envío + tributos |
| Varios productos | Flete sobre el peso total (mínimo 1 kg) y trámite una sola vez; la proforma lleva una fila por producto |
| Tope automático | Si la boleta supera USD 2 000, no se cotiza: el caso pasa a un asesor |
| Vigencia | 24 horas |

| Valor | Peso | TAX (7 %) | Envío | Tributos | Total |
| --: | --: | --: | --: | --: | --: |
| USD 150 | 0.45 kg (se cobra 1 kg) | USD 10.50 | USD 18.00 | USD 0.00 | **USD 178.50** |
| USD 150 | 1.2 kg | USD 10.50 | USD 19.80 | USD 0.00 | **USD 180.30** |
| USD 1 000 | 2.5 kg | USD 70.00 | USD 31.50 | USD 256.80 | **USD 1 358.30** |

---

## 6. Comportamiento conversacional

**Experiencia del cliente**

- **Globix:** se presenta por nombre y aclara que es un asistente virtual. Los textos fijos están aprobados por el equipo: tono cercano, como máximo dos emojis por mensaje y montos siempre como *USD 62.70*.
- **Menú de WhatsApp:** la bienvenida ofrece *Cotizar envío*, *Rastrear paquete* y *Otras consultas* (dirección en Miami, plazos de entrega, entregas en Lima, envíos a provincias, cómo funciona, formas de pago y modalidad viajero). El cliente también puede escribir libremente; si ya dijo qué necesita, no se le muestra el menú. Al recibir un mensaje, el bot lo marca como leído y muestra "escribiendo…".
- **Preguntas frecuentes:** busca la consulta en la base de 132 respuestas aprobadas ([`faq_globex.py`](faq_globex.py), búsqueda tolerante a faltas de ortografía) y envía la respuesta aprobada tal cual. Puede responder varias preguntas en un mismo mensaje. Reempaque, reclamos concretos y compra asistida se derivan al asesor después de responder.
- **Datos para cotizar:** pide en un solo mensaje producto, precio en USD y peso en kg ("Laptop Lenovo, USD 650, 2.5 kg"). Si falta el peso, lo busca en el catálogo; si el producto no está, pregunta solo el peso aproximado. Entiende montos en palabras ("mil dólares", "medio kilo") y pedidos de varios productos.
- **Pedido en curso:** cada dato se guarda en un borrador del pedido ([`borrador.py`](borrador.py)). Globix pide solo lo que falta y, si el cliente corrige un dato, vuelve a cotizar con el dato corregido.
- **Proforma:** la cotización llega como imagen con la marca Globex (producto, flete, trámite aduanero, tributos, total y vigencia), seguida del total y los botones *Hablar con asesor*, *Cotizar otro* y *¿Cómo compro?*. Si la imagen no se puede enviar, se usa un mensaje de texto.
- **Derivación con resumen:** al derivar (pedido del cliente, compra de más de USD 2 000, seguimiento de un paquete, viajero, máximo por categoría excedido o mercancía que requiere revisión), Globix pide el nombre una sola vez, pausa el bot y deja un **resumen del caso** en la consola: motivo, necesidad, cliente, productos (cantidades, tiendas, precio, estado del TAX, peso y total), pendientes y mensajes del cliente. El resumen se arma con datos del sistema, sin LLM.
- **Alcance limitado a Globex:** ante temas ajenos, la herramienta `fuera_de_alcance` envía un texto fijo con el menú; además, toda respuesta libre del LLM pasa por una revisión en código que bloquea código, enlaces, textos de más de 700 caracteres y montos que el cliente no dijo.
- **Recuperación:** si el bot falla dos veces seguidas, ofrece las opciones y el asesor en vez de repetir el error.

**Control de mercancía** ([`guardrails.py`](guardrails.py))

| Categoría | Productos | Qué hace Globix |
| :-- | :-- | :-- |
| Prohibidos | Vapes, armas y municiones, pirotecnia, semillas, sprays, chupones, biberones, pegamento de pestañas | Informa que no se transportan y no cotiza |
| No admitidos | TV Box, artículos y dispositivos médicos | Informa que Globex no los admite y no cotiza |
| Con receta médica visada | Medicinas, vitaminas, proteínas, suplementos | Explica el requisito y deriva al asesor |
| Carga peligrosa | Baterías sueltas, powerbanks | Explica la restricción y deriva al asesor |
| Solo nuevos | Ropa, juguetes y repuestos usados | Informa que solo entran nuevos y no cotiza el usado |
| Máximos por categoría | Calzado 5 pares y juguetes 4 (por consignatario), shampoo 2 (por cotización), perfumes 4, maquillaje 4 y cremas 3 (por DNI) | Cotiza dentro del máximo; si lo supera, deriva antes de pedir precio o peso |

El control trabaja con palabras completas y sin tildes, y entiende negaciones ("no es un vape", "ropa nueva, no usada").

**Reglas de operación**

- **Agrupación de 5 s:** si el cliente escribe varios mensajes seguidos, el bot los une y responde una sola vez.
- **Escape a humano:** el LLM decide si el cliente realmente pide una persona (`derivar_a_asesor`); al derivar, el bot se silencia (`bot_activo = 0`) y el chat pasa a *Listo para Asesor*. Mientras un asesor atiende, el bot no responde encima.
- **Identidad del cliente:** cada chat se identifica con el ID de usuario de Meta (BSUID), que llega aunque el cliente oculte su número. El teléfono se guarda aparte solo como respaldo de envío y no se muestra.
- **Memoria:** el contexto del LLM se reconstruye desde SQLite en cada turno (últimas 12 h, hasta 40 mensajes) e incluye lo que escribió el asesor.
- **Mensajes no textuales:** ante audios, fotos, documentos o videos, el bot avisa que atiende por texto y deja el registro para el asesor.
- **Deduplicación:** los reintentos de Meta con el mismo `wamid` se ignoran; los mensajes que llegan con retraso se responden igual.
- **Recordatorio:** si una cotización queda sin respuesta, se envía un mensaje de seguimiento a los 20 min.
- **Hora de Lima:** todo el sistema usa `America/Lima`, aunque Render y Streamlit Cloud corran en UTC.

---

## 7. Consola de asesores

Aplicación Streamlit ([`dashboard.py`](dashboard.py)) con la marca Globex (logo y colores morado `#2E1A47` y naranja `#FF6900`).

- **Bandeja en tres paneles:** lista de chats ordenada por los que requieren asesor y llevan más tiempo esperando (estado y semáforo de espera) · conversación con formato de WhatsApp y respuesta directa · detalle del lead.
- **Detalle del lead:** resumen del caso, cotización, tiempo de primera atención útil y quién la dio, estado y asignación de asesor. Los chats nuevos quedan *sin asignar*; el primer asesor que responde queda asignado.
- **Revisión de la cotización:** *Validar y enviar PDF* (envía la proforma formal al cliente), *Corregir cotización* y *Reportar error de Globix* por categoría.
- **Indicadores:** conversaciones, casos que requieren asesor, casos con más de 45 min de espera y monto cotizado. Filtros por estado, asesor, servicio y búsqueda; actualización automática.
- **Métricas (administrador):** primera atención útil en ≤ 60 min, costo y latencia de Globix, tipos de respuesta y revisiones del asesor.

---

## 8. Métricas en operación

**Primera atención útil en ≤ 60 min.** Por cada lead se guarda el primer mensaje del cliente y la primera atención útil (momento, actor y tipo). Cuenta como útil una respuesta que atiende la consulta (cotización, pregunta frecuente, explicación de mercancía restringida, primer mensaje de un asesor) o que pide un dato indispensable para avanzar (producto, precio, peso o código de tracking). Un saludo, el menú o pedir el nombre no cuentan. El indicador se reporta con IC 95 % de Clopper-Pearson, junto con la mediana del tiempo y la proporción atendida por Globix y por asesores.

**Costo y latencia por turno** (tabla `metricas_turno`, [`metricas.py`](metricas.py)):

| Campo | Qué mide |
| :-- | :-- |
| `llamadas_llm`, `tokens_entrada`, `tokens_salida` | Uso del LLM en el turno |
| `costo_usd` | Costo estimado con el precio por millón de tokens (configurable) |
| `latencia_llm_ms`, `latencia_procesamiento_ms` | Tiempo del LLM y del procesamiento completo del turno |
| `latencia_total_ms` | Lo que espera el cliente, incluida la agrupación de 5 s |
| `espera_limite_ms` | Espera por límite de cuota del proveedor, separada de la latencia |
| `tipo_respuesta`, `herramientas` | Tipo de respuesta y herramientas llamadas, con argumentos y resultado |

Todo está disponible en `GET /api/metricas` y en la página **Métricas** de la consola.

---

## 9. Evaluación

### Banco final (un comando)

[`evaluacion.py`](evaluacion.py) ejecuta el banco final contra Globix desplegado y genera el informe en PDF. No hace falta instalar el backend ni tener keys de LLM: el chatbot y el juez corren en el servidor.

**Requisitos:** Python 3.10 o superior, la carpeta del banco `Globex_Bancos_V2` (con `00_Indice_Bancos.txt` y `MANIFIESTO_SHA256.txt`) y la clave `EVAL_API_KEY`. El equipo entrega la carpeta y la clave por separado; no están en el repositorio.

```bash
git clone https://github.com/BryanGuerraS/globex-mvp.git
```

```bash
cd globex-mvp
```

```bash
pip install -r requirements-evaluacion.txt
```

Crear un archivo `.env` en la raíz con la línea `EVAL_API_KEY=<clave entregada por el equipo>` y ejecutar:

```bash
python evaluacion.py "<ruta>/Globex_Bancos_V2" --repeticiones 3
```

**Qué hace:**

1. Verifica cada archivo del banco contra su manifiesto SHA-256 y se detiene si alguno cambió.
2. Envía cada caso a Globix por `POST /api/eval/caso`: mismo flujo que WhatsApp, en una conversación nueva y sin enviar mensajes reales.
3. Revisa con los registros del sistema la derivación, el total cotizado y las cotizaciones a pedidos bloqueados.
4. Califica preguntas frecuentes, productos con condiciones especiales y conversaciones con el juez del equipo (prompts del banco).
5. Genera el PDF y un JSON con los 6 indicadores, sus intervalos de confianza al 95 % y sus metas.

| Opción | Qué hace |
| :-- | :-- |
| `--repeticiones N` | Corre el banco N veces y agrega un informe con el resultado de cada corrida, el promedio y el rango; un indicador cumple si su promedio alcanza la meta |
| `--corrida NOMBRE` | Nombre de la corrida; repetir el mismo comando continúa donde quedó, sin repetir casos |
| `--url URL` | Otro servidor de Globix (por defecto, el de Render) |

Los resultados quedan en `evaluacion/reportes/banco_final/<corrida>/` (`Informe_final_<corrida>.pdf`, `resultado.json`, `casos.jsonl` y `juez.jsonl`); con `--repeticiones 3`, el informe combinado queda en `<corrida>-x3/`. Cada corrida tarda unos 18 minutos. Guía de la API: [`docs/api_evaluacion.md`](docs/api_evaluacion.md).

### Motor de cotización

[`evaluacion/casos_motor.json`](evaluacion/casos_motor.json) tiene 60 casos en 10 categorías: flete y peso mínimo, exoneración bajo USD 200, tributos, TAX de tienda, tope de USD 2 000, entradas inválidas, anclaje de los argumentos al mensaje del cliente, anclaje del TAX, cantidades y pedidos de varios productos. Los valores esperados salen de un oráculo independiente en `Decimal` ([`evaluacion/generar_casos_motor.py`](evaluacion/generar_casos_motor.py)) y se comparan al centavo con el motor, el texto de WhatsApp y la validación de argumentos. Resultado: **60/60**.

```bash
python evaluacion/verificar_motor.py
```

### Set de desarrollo con el LLM real

[`evaluacion/evaluar.py`](evaluacion/evaluar.py) corre conversaciones guionadas contra el flujo real de Globix (sin WhatsApp y con una base temporal), repite cada caso para medir consistencia y genera un reporte en PDF, Markdown y JSON con KPIs e IC 95 % (éxito de tarea pass^1 y pass^k, exactitud de herramienta y de argumentos, cotización indebida, derivación, control de mercancía y alcance), costo, latencia y el detalle de cada falla. El set de desarrollo ([`evaluacion/casos_desarrollo.json`](evaluacion/casos_desarrollo.json), 173 casos) sirve para probar y ajustar; las metas mínimas están en [`evaluacion/kpis_minimos.py`](evaluacion/kpis_minimos.py) y el plan en [`docs/plan_evaluacion.md`](docs/plan_evaluacion.md).

```bash
python evaluacion/evaluar.py --repeticiones 3
```

```bash
python evaluacion/evaluar.py --solo COT-01,ALC-02 --repeticiones 1
```

### Pruebas automatizadas

Corren en una carpeta temporal y no tocan `globex.db` ni envían mensajes a Meta:

```bash
python -m pytest tests -q
```

---

## 10. Instalación y ejecución

**Requisitos:** Python 3.10+, una API key de [Groq](https://console.groq.com) y una app de Meta con WhatsApp Cloud API configurada.

```bash
git clone https://github.com/BryanGuerraS/globex-mvp.git
```

```bash
cd globex-mvp
```

```bash
python -m venv .venv
```

Activar el entorno (Windows PowerShell: `.venv\Scripts\Activate.ps1`; Linux/Mac: `source .venv/bin/activate`) e instalar dependencias:

```bash
pip install -r requirements.txt
```

Copiar `.env.example` a `.env` y completar:

| Variable | Uso |
| :-- | :-- |
| `GROQ_API_KEY`, `GROQ_MODEL` | Acceso al LLM (`GROQ_API_KEY_RESPALDO`, `_2`… como respaldo) |
| `META_PHONE_NUMBER_ID`, `META_WABA_ID` | Línea y cuenta de WhatsApp Business |
| `META_ACCESS_TOKEN` | Token permanente de usuario del sistema |
| `META_VERIFY_TOKEN` | Token que se registra en Meta al configurar el webhook |
| `META_APP_SECRET` | App Secret de Meta; valida la firma de los webhooks |
| `DASHBOARD_API_KEY` | Clave compartida entre el backend y la consola |
| `BACKEND_URL` | URL del backend que usa la consola |
| `CHAT_API_KEY` | Opcional: clave de `/api/chat` para conversar con Globix desde otra aplicación |
| `EVAL_API_KEY` | Opcional: clave de la API de evaluación (`/api/eval/*`) |
| `CEREBRAS_API_KEY`, `JUEZ_CEREBRAS_API_KEY` | Opcionales: keys de Cerebras para la API de evaluación y el juez |

Para generar una clave:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

En producción, las variables van en **Render → Environment** (backend) y en **Streamlit Cloud → Secrets** (`BACKEND_URL` y `DASHBOARD_API_KEY`).

Backend:

```bash
uvicorn main:app --reload --port 8000
```

Consola (en otra terminal):

```bash
streamlit run dashboard.py
```

Para que Meta alcance un backend local hace falta exponerlo con un túnel HTTPS (por ejemplo, ngrok) y registrar esa URL + `/meta-webhook` en el webhook de Meta.

---

## 11. Seguridad

| Control | Cómo funciona |
| :-- | :-- |
| Webhook de Meta | Solo acepta POST con firma `X-Hub-Signature-256` válida (`META_APP_SECRET`) |
| Verificación del webhook | Requiere `META_VERIFY_TOKEN`; sin valor por defecto en el código |
| API de la consola | Todo `/api/*` exige el header `X-API-Key` (`DASHBOARD_API_KEY`) |
| API de chat de prueba | `/api/chat` exige su propia clave y la key de Groq de quien llama (no se guarda); límite por minuto; nada sale a Meta. Guía: [`docs/api_chat.md`](docs/api_chat.md) |
| API de evaluación | `/api/eval/*` exige `EVAL_API_KEY`, con límites por minuto y por día; los chats de prueba no salen a Meta ni entran en las métricas |
| Falla cerrada | Si falta una clave, el endpoint rechaza la petición y el arranque lo avisa en los logs |
| Proformas PDF | El nombre del archivo usa un identificador hasheado, no el teléfono del cliente |
| Secretos y datos | `.env`, `globex.db` y `cotizaciones_pdf/` están en `.gitignore` |

---

## 12. Estructura del repositorio

```text
globex-mvp/
├── main.py                      # Backend FastAPI: webhook, orquestación del LLM, APIs de consola, chat y evaluación
├── pricing_engine.py            # Motor determinista de cotización
├── validaciones.py              # Validación de los datos del LLM, nombre del cliente y revisión de salida
├── guardrails.py                # Control de mercancía y máximos por categoría
├── borrador.py                  # Borrador estructurado del pedido en curso
├── resumen_caso.py              # Resumen del caso para el asesor
├── faq_globex.py                # Base de 132 respuestas aprobadas y su búsqueda
├── knowledge_base.py            # Respuestas del menú de consultas
├── product_catalog.py           # Pesos referenciales de productos
├── llm_cliente.py               # Cliente del LLM con keys de respaldo
├── proforma_imagen.py           # Proforma en imagen para WhatsApp
├── pdf_generator.py             # Proforma formal en PDF
├── database.py                  # SQLite: chats, mensajes, estados, deduplicación
├── metricas.py                  # Costo, latencia, KPI de atención e intervalos de confianza
├── dashboard.py                 # Consola de asesores (Streamlit)
├── evaluacion.py                # Evaluación con el banco final en un comando
├── banco_final.py               # Verificación del banco e indicadores con sus metas
├── conocimiento/                # Base de respuestas aprobadas
├── evaluacion/                  # Scripts de evaluación, casos de prueba e informes
├── docs/                        # Guías de las APIs, plan de evaluación y rúbrica
├── tests/                       # Pruebas automatizadas (pytest)
├── assets/                      # Logo y material gráfico de Globex
├── requirements.txt
├── requirements-evaluacion.txt  # Solo lo necesario para correr evaluacion.py
├── Procfile                     # Comando de arranque en Render
└── .env.example                 # Plantilla de variables de entorno (sin secretos)
```

---

## 13. Trabajo futuro

- Aviso inmediato al asesor fuera de la consola cuando entra un caso derivado.
- Embudo de ventas (ganado/perdido) en la consola.
- Transcripción de notas de voz.
- Base de datos persistente y credenciales de la consola fuera del código para producción.
