import glob
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
from datetime import datetime
import json
import os
from typing import Dict, List
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import httpx
from openai import OpenAI

# ✅ AHORA (Con todos los métodos necesarios):
from database import (
    actualizar_clasificacion_chat,
    actualizar_estado_chat,
    calcular_tiempo_relativo,
    es_mensaje_duplicado,
    esta_bot_activo,
    get_connection,  # <-- AGREGAR
    init_db,
    marcar_recordatorio_enviado,
    obtener_chats_para_recordatorio,
    obtener_mensajes_chat,  # <-- AGREGAR
    obtener_todos_los_chats,  # <-- AGREGAR
    registrar_mensaje_entrante,
    registrar_mensaje_saliente,
)
from guardrails import verificar_mercancia_restringida
from knowledge_base import buscar_faq_comercial
from pdf_generator import generar_pdf_cotizacion
from pricing_engine import GlobexPricingEngine
from product_catalog import buscar_peso_producto

load_dotenv()
init_db()

app = FastAPI(title="Globex Atiende - Servidor Oficial Meta Cloud API")

# 1. Configuración de Groq (LLM 120B)
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"
)
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# 2. Configuración de Meta Cloud API
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_WABA_ID = os.getenv("META_WABA_ID", "1827849438216727")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "globex_token_secreto_2026")

SYSTEM_PROMPT = """Eres el asistente virtual oficial de Globex Courier (importaciones USA a Perú).

REGLAS DE DISEÑO CONVERSACIONAL (MOBILE-FIRST):
1. SALUDO CORTO O VACÍO:
   Si el cliente solo dice "Hola", "Buenas" o no especifica nada:
   "¡Hola! Bienvenido a Globex Courier 📦. Te puedo ayudar a cotizar una importación desde USA (Courier o Viajero) o con el seguimiento de un paquete en camino. ¿Qué consulta deseas realizar?"

2. SI EL CLIENTE YA DECLARÓ SU CONSULTA:
   Atiende directamente sin menús repetitivos:

   - CUADRANTE 1 [COTIZACIÓN COURIER (Happy Path)]:
     Pide precio en USD y peso en kg (o usa 'consultar_peso_producto' si es tecnología/consola). Con ambos datos llama de inmediato a 'calcular_cotizacion'.

   - CUADRANTE 2 [SEGUIMIENTO COURIER]:
     Si pregunta por paquetes en camino, tracking o almacén: solicita el código de tracking y llama a 'clasificar_como_seguimiento'.

   - CUADRANTE 3 [COTIZACIÓN VIAJERO]:
     Si menciona "viajero" o "maleta": explica que depende de cupos de vuelo y llama a 'clasificar_como_viajero'.

3. PREGUNTAS GENERALES (FAQs):
   Si preguntan por dirección de Miami, plazos de entrega, envíos a provincias o formas de pago, usa 'consultar_faq_comercial'.

REGLAS DE FORMATO Y ESTILO:
- Respuestas breves: Máximo 2 a 3 oraciones por mensaje.
- Deja saltos de línea limpios entre ideas.
- NUNCA inventes precios ni estados de paquetes."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_peso_producto",
            "description": "Consulta el peso referencial estimado (en kg con empaque) de un producto frecuente (laptops, celulares, consolas).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_producto": {
                        "type": "string",
                        "description": "Nombre del producto (ej: 'iphone 15 pro max', 'macbook').",
                    }
                },
                "required": ["nombre_producto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_cotizacion",
            "description": "Calcula el costo oficial de flete e impuestos SUNAT para Courier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "valor_producto_usd": {
                        "type": "number",
                        "description": "Precio o valor comercial del producto en USD.",
                    },
                    "peso_kg": {
                        "type": "number",
                        "description": "Peso en kilogramos.",
                    },
                },
                "required": ["valor_producto_usd", "peso_kg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_faq_comercial",
            "description": "Consulta información oficial y aprobada de Globex: dirección del almacén en Miami, plazos de entrega, envíos a provincias o métodos de pago.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tema": {
                        "type": "string",
                        "description": "Tema a consultar: 'direccion_miami', 'plazos_entrega', 'provincias', 'como_funciona' o 'pagos'.",
                    }
                },
                "required": ["tema"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clasificar_como_seguimiento",
            "description": "Se activa cuando el cliente consulta por el estado, llegada o tracking de un paquete en curso.",
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_tracking": {
                        "type": "string",
                        "description": "El número de tracking o tienda si fue mencionado.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clasificar_como_viajero",
            "description": "Se activa cuando el cliente consulta por la modalidad de 'Viajero / Maleta'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "detalle": {
                        "type": "string",
                        "description": "Detalle del producto a traer por viajero.",
                    }
                },
            },
        },
    },
]

# Control de sesiones y debouncing
sessions: Dict[str, Dict] = {}
message_buffer: Dict[str, List[str]] = {}
buffer_tasks: Dict[str, asyncio.Task] = {}

@app.post("/test-chiquito")
async def test_chiquito(request: Request):
    body = await request.json()
    print(
        "\n⚡ [DIAGNÓSTICO] ¡Llegó un POST exitoso al servidor local!", body
    )
    return {"status": "recibido_ok"}

def get_or_create_history(chat_id: str) -> List[Dict[str, str]]:
    now = datetime.now()
    if chat_id in sessions:
        ultima_vez = sessions[chat_id].get("last_active", now)
        horas_inactivo = (now - ultima_vez).total_seconds() / 3600
        if horas_inactivo > 12:
            print(f"🔄 [TTL Expirado] Reiniciando contexto para [{chat_id}]")
            sessions[chat_id] = {
                "history": [{"role": "system", "content": SYSTEM_PROMPT}],
                "last_active": now,
            }
        else:
            sessions[chat_id]["last_active"] = now
    else:
        sessions[chat_id] = {
            "history": [{"role": "system", "content": SYSTEM_PROMPT}],
            "last_active": now,
        }
    return sessions[chat_id]["history"]


# 📤 FUNCIÓN OFICIAL PARA ENVIAR MENSAJES VÍA META CLOUD API
async def send_meta_whatsapp_message(to_phone: str, message: str):
    """Envía mensajes usando la Graph API oficial de Meta."""
    url = f"https://graph.facebook.com/v21.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }

    async with httpx.AsyncClient() as http_client:
        try:
            res = await http_client.post(
                url, json=payload, headers=headers, timeout=10.0
            )
            if res.status_code == 200:
                print(f"✅ [Meta Cloud API] Mensaje entregado a [{to_phone}]")
            else:
                print(
                    f"⚠️ Error Meta API ({res.status_code}): {res.text}"
                )
        except Exception as e:
            print(f"❌ Error de conexión al enviar con Meta: {e}")


async def procesar_mensaje_consolidado(
    chat_id: str, sender_name: str, texto_consolidado: str
):
    print(f"\n🚀 Procesando consolidado de [{chat_id}]: '{texto_consolidado}'")

    # 🛑 1. ESCAPE HATCH HUMANO INMEDIATO (T13 / F42)
    palabras_escape = [
        "humano",
        "asesor",
        "persona",
        "operador",
        "llámame",
        "llamar",
        "hablar con alguien",
    ]
    if any(palabra in texto_consolidado.lower() for palabra in palabras_escape):
        print(
            f"👨‍💼 [Escape Hatch] Cliente [{chat_id}] solicitó atención humana directa."
        )
        actualizar_estado_chat(
            chat_id=chat_id, nuevo_estado="Listo para Asesor", bot_activo=0
        )
        bot_reply = (
            "Entendido. He transferido tu solicitud a tu asesor asignado para que continúe la atención "
            "directamente por este chat. Se comunicará contigo a la brevedad."
        )
        registrar_mensaje_saliente(chat_id, "bot", bot_reply, None)
        await send_meta_whatsapp_message(chat_id, bot_reply)
        return

    # 🛡️ 2. GUARDRAIL DE MERCANCÍA RESTRINGIDA / SUNAT (CE11, CE12, F28, F31)
    alerta_aduanera = verificar_mercancia_restringida(texto_consolidado)
    if alerta_aduanera:
        entidad = alerta_aduanera["entidad"]
        print(
            f"🚨 [Guardrail Activado] Mercancía restringida ({entidad}) detectada en [{chat_id}]"
        )
        bot_reply = alerta_aduanera["mensaje"]

        if alerta_aduanera["tipo"] == "prohibido":
            actualizar_clasificacion_chat(
                chat_id, servicio="Mercancía Prohibida", estado="Cerrado", paso=1
            )
        else:
            actualizar_clasificacion_chat(
                chat_id,
                servicio=f"Restringido ({entidad})",
                estado="Listo para Asesor",
                paso=4,
            )
            actualizar_estado_chat(
                chat_id, nuevo_estado="Listo para Asesor", bot_activo=0
            )

        registrar_mensaje_saliente(chat_id, "bot", bot_reply, None)
        await send_meta_whatsapp_message(chat_id, bot_reply)
        return

    # 💬 3. CONVERSACIÓN Y LLAMADA A HERRAMIENTAS (TOOL CALLING)
    history = get_or_create_history(chat_id)
    history.append({"role": "user", "content": texto_consolidado})

    resultado_calculo = None

    try:
        # Llamada en hilo separado para no bloquear el servidor
        ai_response = await asyncio.to_thread(
            client.chat.completions.create,
            model=MODEL,
            messages=history,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        response_message = ai_response.choices[0].message

        if response_message.tool_calls:
            tool_call = response_message.tool_calls[0]
            nombre_funcion = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            # RAG DE PESOS
            if nombre_funcion == "consultar_peso_producto":
                prod_busqueda = args.get("nombre_producto", "")
                info_prod = buscar_peso_producto(prod_busqueda)

                history.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call],
                    }
                )
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": nombre_funcion,
                        "content": json.dumps(
                            info_prod if info_prod else {"encontrado": False}
                        ),
                    }
                )

                segunda_respuesta = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=MODEL,
                    messages=history,
                    tools=TOOLS,
                    temperature=0.2,
                )

                msg_2 = segunda_respuesta.choices[0].message
                if (
                    msg_2.tool_calls
                    and msg_2.tool_calls[0].function.name
                    == "calcular_cotizacion"
                ):
                    args_calc = json.loads(
                        msg_2.tool_calls[0].function.arguments
                    )
                    val = float(args_calc.get("valor_producto_usd", 0))
                    peso = float(args_calc.get("peso_kg", 0))
                    resultado_calculo = GlobexPricingEngine.calcular(val, peso)
                    actualizar_clasificacion_chat(
                        chat_id, servicio="Cotización Courier", paso=3
                    )
                    bot_reply = f"ℹ️ *Peso estimado con caja:* ~{peso} kg\n\n" + GlobexPricingEngine.formatear_mensaje_whatsapp(
                        resultado_calculo
                    )
                else:
                    bot_reply = msg_2.content

            # CÁLCULO DETERMINISTA COURIER
            elif nombre_funcion == "calcular_cotizacion":
                val = float(args.get("valor_producto_usd", 0))
                peso = float(args.get("peso_kg", 0))
                resultado_calculo = GlobexPricingEngine.calcular(val, peso)
                actualizar_clasificacion_chat(
                    chat_id, servicio="Cotización Courier", paso=3
                )
                bot_reply = GlobexPricingEngine.formatear_mensaje_whatsapp(
                    resultado_calculo
                )

            # BASE DE CONOCIMIENTO (FAQs)
            elif nombre_funcion == "consultar_faq_comercial":
                info_faq = buscar_faq_comercial(texto_consolidado)
                bot_reply = (
                    info_faq["contenido"]
                    if info_faq
                    else "Globex realiza envíos de USA a Perú en 5 a 7 días hábiles. ¿Deseas cotizar algún producto?"
                )

            # SEGUIMIENTO
            elif nombre_funcion == "clasificar_como_seguimiento":
                actualizar_clasificacion_chat(
                    chat_id,
                    servicio="Seguimiento Courier",
                    estado="Listo para Asesor",
                    paso=4,
                )
                actualizar_estado_chat(
                    chat_id, nuevo_estado="Listo para Asesor", bot_activo=0
                )
                bot_reply = (
                    "📦 He registrado tu consulta de seguimiento. Tu asesor asignado revisará "
                    "el estado de tu paquete en almacén y te responderá a la brevedad por aquí."
                )

            # VIAJERO
            elif nombre_funcion == "clasificar_como_viajero":
                actualizar_clasificacion_chat(
                    chat_id,
                    servicio="Cotización Viajero",
                    estado="Listo para Asesor",
                    paso=4,
                )
                actualizar_estado_chat(
                    chat_id, nuevo_estado="Listo para Asesor", bot_activo=0
                )
                bot_reply = (
                    "🧳 La modalidad de *Viajero* depende del cupo y fecha de vuelos programados. "
                    "He transferido tu solicitud a nuestro asesor especializado para confirmarte disponibilidad."
                )

            history.append({"role": "assistant", "content": bot_reply})
        else:
            bot_reply = response_message.content
            history.append({"role": "assistant", "content": bot_reply})

    except Exception as e:
        print(f"❌ Error al procesar mensaje: {e}")
        bot_reply = "Disculpa, tuve un inconveniente interno al procesar tu consulta. ¿Podrías repetirla?"

    # 📄 GENERAR PROFORMA PDF SI HUBO COTIZACIÓN
    if resultado_calculo:
        try:
            ruta_pdf = generar_pdf_cotizacion(
                chat_id, sender_name, resultado_calculo
            )
            print(f"📄 [PDF Generado exitosamente]: {ruta_pdf}")
            bot_reply += "\n\n📄 *He emitido tu Proforma Oficial en PDF.* Tu asesor te la puede compartir en cualquier momento."
        except Exception as e:
            print(f"Error generando PDF: {e}")

    registrar_mensaje_saliente(chat_id, "bot", bot_reply, resultado_calculo)
    await send_meta_whatsapp_message(chat_id, bot_reply)


async def debounce_mensajes(chat_id: str, sender_name: str):
    """Ventana deslizante de 5 segundos."""
    try:
        await asyncio.sleep(5.0)
        if chat_id in message_buffer and message_buffer[chat_id]:
            mensajes_juntos = " ".join(message_buffer[chat_id])
            message_buffer[chat_id] = []
            await procesar_mensaje_consolidado(
                chat_id, sender_name, mensajes_juntos
            )
    except asyncio.CancelledError:
        pass


# 🌐 1. ENDPOINT GET: VERIFICACIÓN DEL WEBHOOK DE META (HANDSHAKE)
@app.get("/meta-webhook")
async def verify_meta_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ [Meta Webhook] Handshake verificado exitosamente.")
        return Response(content=challenge, media_type="text/plain")
    return Response(
        content="Token de verificación inválido", status_code=403
    )


# 🌐 2. ENDPOINT POST: RECEPCIÓN OFICIAL DE MENSAJES DE META
@app.post("/meta-webhook")
async def meta_webhook(request: Request):
    data = await request.json()

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})

        # Validar si el evento trae mensajes de WhatsApp
        messages = value.get("messages", [])
        if not messages:
            # Podría ser un cambio de estado (sent, delivered, read) u otro evento
            return {"status": "event_without_messages"}

        msg = messages[0]
        chat_id = msg.get("from")  # Teléfono del cliente
        msg_type = msg.get("type")
        id_message = msg.get("id")

        # Nombre del cliente provisto por Meta
        contacts = value.get("contacts", [])
        sender_name = (
            contacts[0].get("profile", {}).get("name", "Cliente")
            if contacts
            else "Cliente"
        )

        # 🛡️ PASO HP01: DEDUPLICACIÓN
        if id_message and es_mensaje_duplicado(id_message):
            print(f"⚠️ [Deduplicación HP01] Mensaje Meta [{id_message}] ya procesado.")
            return {"status": "duplicate_ignored"}

        # 🖼️🎙️ TRATAMIENTO DE NO-TEXTUALES
        if msg_type in ["image", "audio", "document", "video"]:
            tipo_adjunto = (
                "audio 🎙️"
                if msg_type == "audio"
                else "imagen 📷"
                if msg_type == "image"
                else "documento 📄"
            )
            print(f"\n📎 Archivo no textual ({msg_type}) recibido de [{chat_id}]")
            registrar_mensaje_entrante(
                chat_id,
                sender_name,
                f"[{tipo_adjunto.upper()} ADJUNTO]",
                id_mensaje=id_message,
            )

            if not esta_bot_activo(chat_id):
                return {"status": "bot_silenced_for_human"}

            bot_reply = (
                f"He recibido tu {tipo_adjunto}. Por el momento atiendo consultas por texto.\n\n"
                f"¿Podrías escribir brevemente tu consulta o describir el producto para ayudarte con tu cotización?"
            )
            registrar_mensaje_saliente(chat_id, "bot", bot_reply, None)
            await send_meta_whatsapp_message(chat_id, bot_reply)
            return {"status": "media_handled"}

        # 💬 MENSAJES DE TEXTO
        if msg_type == "text":
            user_text = msg.get("text", {}).get("body", "").strip()
            print(f"\n📩 [Meta] Mensaje de {sender_name} [{chat_id}]: {user_text}")

            registrar_mensaje_entrante(
                chat_id, sender_name, user_text, id_mensaje=id_message
            )

            # Silencio si el asesor humano tiene el control
            if not esta_bot_activo(chat_id):
                print(
                    f"🤫 [Bot Silenciado] El chat [{chat_id}] está bajo atención humana."
                )
                return {"status": "bot_silenced_for_human"}

            # Debouncing de 5 segundos
            if chat_id not in message_buffer:
                message_buffer[chat_id] = []
            message_buffer[chat_id].append(user_text)

            if chat_id in buffer_tasks and not buffer_tasks[chat_id].done():
                buffer_tasks[chat_id].cancel()

            buffer_tasks[chat_id] = asyncio.create_task(
                debounce_mensajes(chat_id, sender_name)
            )

    except Exception as e:
        print(f"Error procesando webhook de Meta: {e}")

    return {"status": "ok"}


# ⏰ TRABAJADOR DE FONDO: AUTO-NUDGE DE 20 MINUTOS
async def tarea_fondo_recordatorios():
    while True:
        try:
            await asyncio.sleep(60)
            chats_pendientes = obtener_chats_para_recordatorio()
            for c in chats_pendientes:
                ultimo_msg = c.get("ultimo_mensaje_cliente_at")
                if ultimo_msg:
                    tiempo = calcular_tiempo_relativo(ultimo_msg)
                    if tiempo["minutos"] >= 20:
                        chat_id = c["chat_id"]
                        nombre = c["nombre"]
                        monto = c["cotizacion_total"]
                        msg_nudge = (
                            f"¡Hola {nombre}! 👋 Te escribo de Globex para recordarte que tu cotización "
                            f"de ${monto:,.2f} USD sigue activa en nuestro sistema.\n\n"
                            f"¿Deseas que procedamos a asignarte tu casillero en Miami para realizar tu compra?"
                        )
                        print(
                            f"⚡ [Auto-Nudge] Recordatorio enviado a [{chat_id}]"
                        )
                        await send_meta_whatsapp_message(chat_id, msg_nudge)
                        registrar_mensaje_saliente(
                            chat_id, "bot (auto-recordatorio)", msg_nudge
                        )
                        marcar_recordatorio_enviado(chat_id)
        except Exception as e:
            print(f"Error en worker de recordatorios: {e}")


# 🔗 FUNCIÓN DE AUTO-SUSCRIPCIÓN DE LA WABA A LA APP (Solución del Shadow Delivery)
async def auto_suscribir_waba_a_la_app():
    """Suscribe automáticamente la WABA de Meta a los eventos de la App para que lleguen los mensajes reales."""
    url = f"https://graph.facebook.com/v21.0/{META_WABA_ID}/subscribed_apps"
    headers = {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}
    async with httpx.AsyncClient() as client_http:
        try:
            res = await client_http.post(url, headers=headers, timeout=10.0)
            if res.status_code == 200 and res.json().get("success"):
                print(
                    "🎉 [Meta WABA] Cuenta de WhatsApp suscrita a la App exitosamente (Entrega desbloqueada)."
                )
            else:
                print(f"ℹ️ [Meta WABA Sync]: {res.text}")
        except Exception as e:
            print(f"Advertencia al suscribir WABA: {e}")


@app.on_event("startup")
async def startup_event():
    # 1. Suscribe automáticamente la WABA a la App para recibir mensajes reales
    asyncio.create_task(auto_suscribir_waba_a_la_app())
    # 2. Inicia el worker de recordatorios
    asyncio.create_task(tarea_fondo_recordatorios())


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Globex Atiende Meta Cloud API Oficial",
        "model": MODEL,
        "database": "SQLite (globex.db)",
    }


class MensajeAsesorPayload(BaseModel):
    chat_id: str
    nombre_asesor: str
    texto: str


class ActualizarEstadoPayload(BaseModel):
    chat_id: str
    nuevo_estado: str
    nuevo_asesor: str = None
    bot_activo: int = None


@app.get("/api/chats")
def api_obtener_chats():
    """Devuelve la lista completa de chats y sus estados para el Dashboard."""
    return obtener_todos_los_chats()


@app.get("/api/messages/{chat_id}")
def api_obtener_mensajes(chat_id: str):
    """Devuelve el historial de mensajes de un chat específico."""
    return obtener_mensajes_chat(chat_id)


@app.post("/api/send-advisor-message")
async def api_enviar_mensaje_asesor(payload: MensajeAsesorPayload):
    """Permite al asesor humano enviar un mensaje a WhatsApp desde el Dashboard."""
    clean_phone = payload.chat_id.replace("@c.us", "").strip()
    await send_meta_whatsapp_message(clean_phone, payload.texto)
    registrar_mensaje_saliente(
        payload.chat_id, payload.nombre_asesor, payload.texto
    )
    actualizar_estado_chat(
        payload.chat_id, "Listo para Asesor", bot_activo=0
    )
    return {"status": "sent"}


@app.post("/api/update-chat-status")
def api_actualizar_estado(payload: ActualizarEstadoPayload):
    """Permite al asesor cambiar el estado de un lead o reactivar el bot."""
    actualizar_estado_chat(
        payload.chat_id,
        payload.nuevo_estado,
        payload.nuevo_asesor,
        payload.bot_activo,
    )
    return {"status": "updated"}


@app.get("/api/download-pdf/{chat_id}")
def api_descargar_pdf(chat_id: str):
    """Permite al asesor descargar el PDF oficial generado en el servidor."""
    numero_limpio = chat_id.replace("@c.us", "")
    carpeta_pdf = "cotizaciones_pdf"
    if os.path.exists(carpeta_pdf):
        pdfs = [
            f
            for f in os.listdir(carpeta_pdf)
            if f.startswith(f"Proforma_Globex_{numero_limpio}")
        ]
        if pdfs:
            pdfs.sort(reverse=True)
            ruta_pdf = os.path.join(carpeta_pdf, pdfs[0])
            return FileResponse(
                ruta_pdf, media_type="application/pdf", filename=pdfs[0]
            )
    return Response(content="PDF no encontrado", status_code=404)


@app.post("/api/admin/clean-data")
def api_limpiar_datos():
    """Limpia la base de datos de pruebas y borra los PDFs acumulados en Render."""
    # 1. Limpiar SQLite
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages;")
        cursor.execute("DELETE FROM chats;")
        cursor.execute("VACUUM;")
        conn.commit()

    # 2. Borrar PDFs
    carpeta_pdf = "cotizaciones_pdf"
    borrados = 0
    if os.path.exists(carpeta_pdf):
        archivos = glob.glob(os.path.join(carpeta_pdf, "*.pdf"))
        for f in archivos:
            os.remove(f)
        borrados = len(archivos)

    return {"status": "cleaned", "pdfs_borrados": borrados}