# 📦 GLOBEX ATIENDE — ASISTENTE INTELIGENTE & PANEL OPERATIVO MULTI-AGENTE

**Proyecto Integrador (Capstone Project I)**  
*Maestría en Ciencia de Datos e Inteligencia Artificial — Universidad de Ingeniería y Tecnología (UTEC)*  
*Fecha: Octubre 2026*  

---

## 🎯 1. RESUMEN EJECUTIVO Y PROBLEMA DE NEGOCIO

Globex Courier es una empresa peruana especializada en la importación y transporte de compras desde Estados Unidos (almacén en Miami, Florida) hacia Lima y provincias de Perú. 

### El Problema Operativo (As-Is):
* **Sobrecarga Operativa:** Los cuatro (4) asesores comerciales de Globex deben alternar simultáneamente entre la atención de consultas comerciales en WhatsApp y la logística física de recepción, pesaje y despacho de paquetes en almacén (*"ellos no solo asesoran, sino también embarcan"*).
* **Fuga de Clientes (Leads Perdidos):** En el histórico de 3 años de la empresa, **1,804 prospectos calificados (41% de los evaluables)** no volvieron a escribir tras experimentar una primera respuesta tardía (> 60 minutos).
* **Línea Base:** Solo el 32% de los prospectos recibe una primera respuesta útil dentro de la primera hora.
* **Impacto Económico Cuantificado:** Asumiendo una tasa de conversión conservadora del 35% y un margen promedio de $45 USD por envío, la fuga representa una pérdida estimada de **~$9,465 USD anuales**.

### La Solución Implementada (To-Be):
**Globex Atiende** es un Producto de Datos *End-to-End* que automatiza el 60% de las consultas estándar (*Happy Path*): orienta al usuario, recupera especificaciones técnicas de productos mediante RAG, calcula cotizaciones determinísticas con impuestos de aduana SUNAT exactos, genera proformas formales en PDF y transfiere leads listos para compra a una consola web para los asesores comerciales.

---

## 🏛️ 2. ARQUITECTURA TÉCNICA DEL SISTEMA

El sistema opera bajo un desacoplamiento estricto de 5 capas:

[ CLIENTE EN WHATSAPP ] │ (Mensaje de texto, audio o foto) ▼ [ GREEN API GATEWAY
] │ (Webhook HTTP POST en tiempo real) ▼ [ TÚNEL NGROK (Puerto 8000) ] │
(Redirección segura a localhost) ▼ [ BACKEND FASTAPI (main.py) ] ◄──► [ BASE DE
DATOS LOCAL (globex.db - SQLite) ] │ │ ├── [ Buffer Debounce 5s ] └── Registra
mensajes, estados y tiempos ├── [ Guardrail Mercancía Restringida (DIGEMID /
SUNAT) ] ├── [ Escape Hatch Humano Inmediato (T13) ] │ ▼ (Consulta con Tool /
Function Calling) [ GROQ INFERENCE ENGINE (openai/gpt-oss-120b) ] │ ├── Tool 1:
consultar_peso_producto() ──► [ RAG Catálogo (product_catalog.py) ] ├── Tool 2:
calcular_cotizacion() ──► [ Motor SUNAT (pricing_engine.py) ] └── Tool 3:
consultar_faq_globex() ──► [ Base de Conocimiento (knowledge_base.py) ] │ ▼
(Generación de Proforma) [ GENERADOR DE PDF (pdf_generator.py - ReportLab) ] │
├── Despacho automático de respuesta a WhatsApp (Green API) └──
Sincronización en vivo cada 3s (@st.fragment) │ ▼ [ CONSOLA MULTI-AGENTE
STREAMLIT (dashboard.py) ] • Login para los 4 Asesores + Director (Diego) •
Tarjetas de clientes con avance del Happy Path (🟢 🟢 🟡 ⚪ ⚪) • Semáforo de tiempo
de espera (🟢 <15m, 🟡 15-45m, 🔴 >45m) • Envío de respuestas manuales limpias a
WhatsApp • Carga y despacho de Proformas PDF oficiales con 1 clic


---

## ⚙️ 3. REGLAS DE NEGOCIO Y MOTOR MATEMÁTICO (SUNAT)

Para evitar alucinaciones numéricas del LLM, el cálculo financiero es 100% determinístico en Python puro (`pricing_engine.py`):

1. **Costo de Envío Internacional:**  
   $$\text{Flete} = (\text{Peso en Kg} \times \$9.00\text{ USD}) + \$9.00\text{ USD (Trámite documentario fijo)}$$

2. **Base Imponible Aduanera (Valor CIF):**  
   $$\text{CIF} = \text{Valor Comercial Declarado (FOB)} + \text{Costo de Envío}$$

3. **Tributos de Importación SUNAT (Decreto Legislativo N° 1053):**  
   * **Si Valor FOB $\le$ $200 USD:** Impuesto SUNAT = **$0.00 USD** (Exoneración legal de envíos courier).
   * **Si Valor FOB $>$ $200 USD:** Impuesto SUNAT = **22.72% sobre el valor CIF** (4% Ad-Valorem + 16% IGV + 2% IPM).

4. **Total de la Operación:**  
   $$\text{Total} = \text{Valor Producto} + \text{Costo Envío} + \text{Tributos SUNAT}$$

---

## 🛡️ 4. MEJORES PRÁCTICAS CONVERSACIONALES Y GUARDRAILS

* **Debouncing con Ventana Deslizante (5.0 segundos):** Si el cliente envía fragmentos seguidos (*"Hola"* $\rightarrow$ *"quiero una laptop"* $\rightarrow$ *"cuesta 800"*), el servidor espera 5 segundos, une los textos y responde una sola vez de forma coherente.
* **Tratamiento de No-Textuales (OBS01 / T11):** Si el usuario envía audios, fotos o PDFs, el bot no se cuelga ni se queda mudo; avisa educadamente que atiende por texto y almacena la referencia para el asesor en el dashboard.
* **Escape Hatch Humano Inmediato (T13 / F42):** Si el usuario escribe *"asesor"*, *"persona"* o *"humano"*, el bot se silencia (`bot_activo = 0`), marca el chat como `Listo para Asesor` y cede el control a la consola de Streamlit.
* **Interruptor de Silencio:** Mientras un asesor conversa con el cliente desde la web, el LLM queda bloqueado para no responder encima de la persona.
* **Guardrail de Mercancía Restringida (CE11 / CE12 / F28 / F31):** Bloquea automáticamente la cotización de perfumes, cosméticos y vitaminas (alerta de DIGEMID), y de vapes, armas y pirotecnia (prohibición SUNAT), derivando el caso a revisión humana.
* **Auto-Nudge de 20 Minutos:** Tarea en segundo plano que detecta cotizaciones en silencio por más de 20 minutos y envía un mensaje proactivo para evitar la pérdida del lead.

---

## 📁 5. ESTRUCTURA DEL REPOSITORIO

```text
globex-mvp/
├── .env.example            # Plantilla de variables de entorno (sin secretos)
├── .gitignore              # Protección contra subida de .env, DB y PDFs
├── requirements.txt        # Dependencias congeladas del proyecto
├── README.md               # Documentación integral de arquitectura y uso
│
├── main.py                 # Backend FastAPI: Webhook Green API, orquestador de IA y Debounce
├── database.py             # Capa de datos SQLite (globex.db), migraciones y métricas
├── pricing_engine.py       # Motor determinístico de fletes y aranceles SUNAT
├── product_catalog.py      # Base de conocimiento RAG para deducción de pesos de productos
├── guardrails.py           # Escudo aduanero: detección de mercancías DIGEMID / Prohibidas
├── knowledge_base.py       # Fichas comerciales oficiales (Dirección Miami, Plazos, Provincias)
├── pdf_generator.py        # Generador de proformas corporativas en PDF (ReportLab)
│
├── dashboard.py            # Consola web Streamlit para los 4 asesores comerciales
└── cotizaciones_pdf/       # Directorio local generado con los PDFs de cotización

🚀 6. GUÍA DE INSTALACIÓN Y DESPLIEGUE LOCAL

Requisitos Previos:

  - Python 3.10 o superior instalado.
  - Cuenta gratuita en Groq Console (console.groq.com).
  - Cuenta en Green API (green-api.com) con instancia de WhatsApp vinculada.
  - ngrok instalado (ngrok.com).

Paso 1: Clonar el repositorio y configurar el entorno

git clone https://github.com/TU_USUARIO/globex-mvp.git
cd globex-mvp

# Crear y activar entorno virtual
python -m venv .venv

# En Windows:
.venv\Scripts\Activate.ps1
# En Linux/Mac:
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

Paso 2: Configurar las variables de entorno (.env)

Crear el archivo .env en la raíz copiando el archivo de ejemplo:

cp .env.example .env

Llenar las claves correspondientes en .env:

GROQ_API_KEY=gsk_tu_clave_de_groq_aqui
GROQ_MODEL=openai/gpt-oss-120b

GREEN_API_URL=https://7107.api.greenapi.com
GREEN_ID_INSTANCE=tu_id_instance
GREEN_API_TOKEN=tu_api_token_aqui

Paso 3: Ejecutar los servicios (3 terminales requeridas)

  - Terminal 1: Servidor Backend (FastAPI)

    uvicorn main:app --reload --port 8000

  - Terminal 2: Túnel Seguro de Red (ngrok)

    ngrok http 8000

    Nota: Copiar la URL pública generada (ej. https://xxxx.ngrok-free.dev) y
    pegarla en el panel de Green API en la casilla Webhook Url agregando
    /green-api-webhook al final, activando la opción Receive webhooks on
    incoming messages and files en Yes.

  - Terminal 3: Consola Web de Asesores (Streamlit)

    streamlit run dashboard.py --server.port 8501

    Acceso al Dashboard: Navegar a http://localhost:8501 e ingresar con las
    credenciales:

      - Usuario: carlos (o diego, maria, juan, bryan)
      - Contraseña: 123

🧪 7. CASOS DE PRUEBA Y VALIDACIÓN FUNCIONAL

| ID       | Escenario de Prueba               | Mensaje en WhatsApp                                                      | Comportamiento Esperado                                                                            |
| :------- | :-------------------------------- | :----------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------- |
| **CP01** | Cotización Directa (Happy Path)   | *"Hola, quiero traer una laptop de 1000 dólares que pesa 2.5 kg a Lima"* | Calcula Flete ($31.50) + SUNAT ($211.63) = Total $1,143.13 USD. Genera proforma PDF correlativa.   |
| **CP02** | RAG de Pesos Automático           | *"Quiero cotizar un iPhone 15 Pro Max de 1100 dólares"*                  | Recupera peso referencial con empaque (\~0.45 kg) del catálogo y emite cotización sin repreguntar. |
| **CP03** | Consulta de Dirección Miami (F21) | *"¿Cuál es la dirección del almacén en Miami para poner en Amazon?"*     | Devuelve plantilla exacta de Doral, Florida con Zip Code 33122 y formato de código GX.             |
| **CP04** | Consulta de Plazos y Provincias   | *"¿Cuánto demora en llegar y envían a Trujillo?"*                        | Informa 5 a 7 días hábiles desde recepción en Miami y confirma envío nacional vía Shalom/Olva.     |
| **CP05** | Guardrail DIGEMID (CE11)          | *"Quiero traer 3 perfumes de Victoria's Secret por $150"*                | Bloquea cotización automática, advierte regulación de DIGEMID y transfiere al asesor.              |
| **CP06** | Guardrail Mercancía Prohibida     | *"Quiero importar unos vapes con pods"*                                  | Rechaza el traslado por normativa aduanera SUNAT y seguridad aérea.                                |
| **CP07** | Salida Humana Directa (T13)       | *"Quiero hablar con un asesor por favor"*                                | Silencia el bot (`bot_activo = 0`), avisa al usuario y asigna el chat a la consola web.            |
| **CP08** | Intervención del Asesor           | Escribir desde el Dashboard y pulsar *"Enviar Mensaje a WhatsApp"*       | Llega el mensaje limpio al celular del cliente sin emojis de sistema.                              |
| **CP09** | Despacho de Documento PDF         | Pulsar *"Enviar Proforma Oficial a WhatsApp"* en Dashboard               | El cliente recibe el archivo PDF adjunto en su chat de WhatsApp.                                   |
