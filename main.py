from fastapi import BackgroundTasks, FastAPI, Request
import asyncio
from datetime import datetime
import json
import os
from typing import Dict, List
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import httpx
from openai import OpenAI

# Módulos propios del proyecto Globex
from database import (
    actualizar_clasificacion_chat,
    actualizar_estado_chat,
    calcular_tiempo_relativo,
    es_mensaje_duplicado,
    esta_bot_activo,
    init_db,
    marcar_recordatorio_enviado,
    obtener_chats_para_recordatorio,
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

app = FastAPI(title="Globex Atiende - Backend Oficial Green API")

# 1. Configuración de Groq (LLM 120B)
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"
)
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# 2. Configuración de Green API
GREEN_API_URL = os.getenv("GREEN_API_URL", "https://7107.api.greenapi.com")
ID_INSTANCE = os.getenv("GREEN_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")

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

sessions: Dict[str, Dict] = {}
message_buffer: Dict[str, List[str]] = {}
buffer_tasks: Dict[str, asyncio.Task] = {}


def get_or_create_history(chat_id: str) -> List[Dict[str, str]]:
    """Mantiene la memoria completa de toda la conversación del cliente."""
    now = datetime.now()
    if chat_id in sessions:
        ultima_vez = sessions[chat_id].get("last_active", now)
        horas_inactivo = (now - ultima_vez).total_seconds() / 3600

        # Si pasaron más de 12 horas sin hablar, reinicia limpio
        if horas_inactivo > 12:
            print(
                f"🔄 [TTL Expirado] Reiniciando contexto limpio para [{chat_id}] tras {horas_inactivo:.1f}h"
            )
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

    # Devuelve el historial íntegro sin ningún recorte
    return sessions[chat_id]["history"]


async def send_whatsapp_message(chat_id: str, message: str):
    """Envía un mensaje de texto oficial usando Green API."""
    url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": message}

    async with httpx.AsyncClient() as http_client:
        try:
            res = await http_client.post(url, json=payload, timeout=10.0)
            if res.status_code == 200:
                print(f"✅ [Green API] Mensaje entregado a [{chat_id}]")
            else:
                print(
                    f"⚠️ Error Green API ({res.status_code}): {res.text}"
                )
        except Exception as e:
            print(f"❌ Error de conexión al enviar con Green API: {e}")


async def procesar_mensaje_consolidado(
    chat_id: str, sender_name: str, texto_consolidado: str
):
    print(f"\n🚀 Procesando consolidado de [{chat_id}]: '{texto_consolidado}'")

    # 🛑 1. ESCAPE HATCH HUMANO INMEDIATO (T13 / F42 del Manual)
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
        await send_whatsapp_message(chat_id, bot_reply)
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
        await send_whatsapp_message(chat_id, bot_reply)
        return

    # 💬 3. CONVERSACIÓN Y TOOL CALLING CON GROQ
    history = get_or_create_history(chat_id)
    history.append({"role": "user", "content": texto_consolidado})

    resultado_calculo = None

    try:
        # Llamada asíncrona a Groq para no congelar el servidor
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

            # CÁLCULO DIRECTO DETERMINISTA
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

            # CONSULTA DE FAQs DE GLOBEX
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
    await send_whatsapp_message(chat_id, bot_reply)


async def debounce_mensajes(chat_id: str, sender_name: str):
    """Ventana deslizante de 5 segundos."""
    try:
        await asyncio.sleep(2.5)
        if chat_id in message_buffer and message_buffer[chat_id]:
            mensajes_juntos = " ".join(message_buffer[chat_id])
            message_buffer[chat_id] = []
            await procesar_mensaje_consolidado(
                chat_id, sender_name, mensajes_juntos
            )
    except asyncio.CancelledError:
        pass


# 🌐 ENDPOINT DE RECEPCIÓN GREEN API
@app.post("/green-api-webhook")
async def green_api_webhook(
    request: Request, background_tasks: BackgroundTasks
):
    """Responde 200 OK a Green API en 1 milisegundo para que NUNCA encole mensajes."""
    data = await request.json()

    if data.get("typeWebhook") == "incomingMessageReceived":
        id_message = data.get("idMessage")

        if id_message and es_mensaje_duplicado(id_message):
            return {"status": "duplicate_ignored"}

        message_data = data.get("messageData", {})
        type_message = message_data.get("typeMessage")
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId")
        sender_name = sender_data.get("senderName", "Cliente")

        # 🖼️🎙️ Archivos no textuales
        if type_message in ["audioMessage", "imageMessage", "documentMessage"]:
            tipo_adjunto = (
                "audio 🎙️"
                if type_message == "audioMessage"
                else "imagen 📷"
                if type_message == "imageMessage"
                else "documento 📄"
            )
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
            background_tasks.add_task(send_whatsapp_message, chat_id, bot_reply)
            return {"status": "media_handled"}

        # 💬 Mensajes de texto
        if type_message == "textMessage":
            user_text = message_data.get("textMessageData", {}).get(
                "textMessage", ""
            )

            registrar_mensaje_entrante(
                chat_id, sender_name, user_text, id_mensaje=id_message
            )

            if not esta_bot_activo(chat_id):
                return {"status": "bot_silenced_for_human"}

            if chat_id not in message_buffer:
                message_buffer[chat_id] = []
            message_buffer[chat_id].append(user_text)

            if chat_id in buffer_tasks and not buffer_tasks[chat_id].done():
                buffer_tasks[chat_id].cancel()

            # Debouncing en background task
            buffer_tasks[chat_id] = asyncio.create_task(
                debounce_mensajes(chat_id, sender_name)
            )

    # Devolvemos 200 OK instantáneo para que Green API no encole
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
                        await send_whatsapp_message(chat_id, msg_nudge)
                        registrar_mensaje_saliente(
                            chat_id, "bot (auto-recordatorio)", msg_nudge
                        )
                        marcar_recordatorio_enviado(chat_id)
        except Exception as e:
            print(f"Error en worker de recordatorios: {e}")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(tarea_fondo_recordatorios())


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Globex Atiende Green API",
        "model": MODEL,
        "database": "SQLite (globex.db)",
    }