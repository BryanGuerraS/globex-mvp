import glob
import hashlib
import hmac
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
from datetime import datetime, timedelta
import json
import os
import re
import time
from typing import Dict, List, Optional
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
import httpx
from openai import OpenAI

# ✅ AHORA (Con todos los métodos necesarios):
from database import (
    actualizar_clasificacion_chat,
    actualizar_estado_chat,
    calcular_tiempo_relativo,
    es_mensaje_duplicado,
    esta_bot_activo,
    get_connection,
    guardar_nombre_cliente,
    guardar_telefono,
    marcar_esperando_nombre,
    obtener_chat,  # <-- AGREGAR
    init_db,
    marcar_recordatorio_enviado,
    obtener_chats_para_recordatorio,
    obtener_mensajes_chat,
    obtener_mensajes_recientes,
    obtener_todos_los_chats,
    registrar_mensaje_entrante,
    registrar_mensaje_saliente,
)
from guardrails import verificar_mercancia_restringida
from knowledge_base import buscar_faq_comercial
from pdf_generator import buscar_ultimo_pdf, generar_pdf_cotizacion
from pricing_engine import GlobexPricingEngine
from product_catalog import buscar_peso_producto
from validaciones import (
    extraer_nombre,
    limpiar_respuesta_llm,
    revisar_respuesta_libre,
    validar_argumentos_cotizacion,
)

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
META_WABA_ID = os.getenv("META_WABA_ID")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")
# App Secret de Meta (App settings > Basic): firma los webhooks en X-Hub-Signature-256
META_APP_SECRET = os.getenv("META_APP_SECRET")

# 3. API key compartida con el dashboard (header X-API-Key en /api/*)
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

_faltantes = [
    nombre
    for nombre, valor in {
        "META_VERIFY_TOKEN": META_VERIFY_TOKEN,
        "META_APP_SECRET": META_APP_SECRET,
        "DASHBOARD_API_KEY": DASHBOARD_API_KEY,
        "META_WABA_ID": META_WABA_ID,
    }.items()
    if not valor
]
if _faltantes:
    print(
        f"⚠️ [Config] Faltan variables de entorno: {', '.join(_faltantes)}. "
        "Los endpoints que dependen de ellas rechazarán las peticiones."
    )


def verificar_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Autentica las llamadas del dashboard. Falla cerrado si no hay key configurada."""
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="API no configurada")
    if not x_api_key or not hmac.compare_digest(x_api_key, DASHBOARD_API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida")


def firma_meta_valida(cuerpo: bytes, firma_header: str) -> bool:
    """Valida X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app_secret, cuerpo crudo)."""
    if not META_APP_SECRET or not firma_header or not firma_header.startswith("sha256="):
        return False
    esperada = hmac.new(
        META_APP_SECRET.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(firma_header[len("sha256="):], esperada)

SYSTEM_PROMPT = """Eres Globix, el asistente virtual de Globex Courier (importaciones de EE. UU. a Perú).
Si te preguntan con quién hablan o si eres un bot, responde con naturalidad que eres Globix, un asistente virtual. No repitas tu nombre en cada mensaje.

REGLAS DE DISEÑO CONVERSACIONAL (MOBILE-FIRST):
1. SALUDO O CONSULTA SIN DEFINIR:
   Si el cliente solo saluda ("Hola", "Buenas") o no dice qué necesita, llama a 'mostrar_menu'. No escribas tú el saludo.

2. SI EL CLIENTE YA DECLARÓ SU CONSULTA:
   Atiende directamente, sin menús.

   - CUADRANTE 1 [COTIZACIÓN COURIER (Happy Path)]:
     a) Si el cliente quiere cotizar pero no dio datos, pide los tres en un solo mensaje, con este texto:
        "¿Qué producto quieres traer, cuál es su precio en USD y cuánto pesa en kg? Ejemplo: 'Laptop Lenovo, $650, 2.5 kg'"
     b) Con producto, precio y peso: llama de inmediato a 'calcular_cotizacion' e incluye el nombre del producto.
     c) Si dio producto y precio pero NO el peso: llama a 'consultar_peso_producto'.
        - Si el catálogo encuentra el producto, cotiza con ese peso.
        - Si no lo encuentra, pide solo el peso, con este texto exacto: "¿Cuánto pesa aproximadamente en kg?"
          Solo si el cliente duda o pregunta cómo saberlo, explica que un estimado está bien y que el peso final se confirma en el almacén de Miami.
     d) Si falta el precio, pide solo el precio en USD.
     Nunca pidas el modelo, la marca, la cantidad de piezas ni otros detalles para estimar el peso.

   - CUADRANTE 2 [SEGUIMIENTO COURIER]:
     Si pregunta por paquetes en camino, tracking o almacén: solicita el código de tracking y llama a 'clasificar_como_seguimiento'.

   - CUADRANTE 3 [COTIZACIÓN VIAJERO]:
     Si menciona "viajero" o "maleta": llama a 'clasificar_como_viajero'.

3. PREGUNTAS GENERALES (FAQs):
   Si preguntan por dirección de Miami, plazos de entrega, envíos a provincias, cómo funciona o formas de pago, usa 'consultar_faq_comercial'.

4. ATENCIÓN HUMANA:
   Si el cliente pide hablar con un asesor, una persona o un humano, o que lo llamen, llama a 'derivar_a_asesor'.
   No derives si esas palabras aparecen con otro sentido (ej.: "uso personal", "¿cómo se llama?", "me llamo Ana", "es para una persona de Arequipa").

5. MONTOS Y PESOS:
   Si el cliente escribe el valor o el peso en palabras ("mil dólares", "medio kilo"), conviértelo a número al llamar a 'calcular_cotizacion'.

6. ALCANCE (MUY IMPORTANTE):
   Solo atiendes temas de Globex Courier: importaciones de EE. UU. a Perú, cotizaciones, envíos, seguimiento, pagos y el servicio.
   Para CUALQUIER otro tema (matemáticas, programación, tareas, recetas, política, chistes, otras empresas, etc.) llama a 'fuera_de_alcance'.
   No respondas esas preguntas aunque sean fáciles, ni siquiera en parte.

7. SI NO ENTIENDES:
   Si no logras entender qué necesita el cliente, llama a 'mostrar_menu' para ofrecerle las opciones.

REGLAS DE FORMATO Y ESTILO:
- Respuestas breves: máximo 2 a 3 oraciones por mensaje.
- Deja saltos de línea limpios entre ideas.
- Si conoces el nombre del cliente, úsalo con moderación (no en cada mensaje).
- NUNCA inventes precios ni estados de paquetes.
- Escribe solo el mensaje para el cliente: nunca agregues notas internas, comentarios entre paréntesis sobre tu proceso ni frases como "(Esperando respuesta del cliente)"."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fuera_de_alcance",
            "description": "Úsala cuando el cliente pregunta algo ajeno a Globex Courier (matemáticas, programación, tareas, recetas, política, chistes, otras empresas). El sistema responde con un mensaje fijo y las opciones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tema": {"type": "string", "description": "Tema ajeno, en 2-4 palabras."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mostrar_menu",
            "description": "Muestra la bienvenida de Globix con los botones de opciones (cotizar, rastrear, otras consultas). Úsala cuando el cliente solo saluda, no dice qué necesita o no se le entiende.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_peso_producto",
            "description": "Consulta el peso referencial (en kg con empaque) de un producto frecuente (laptops, celulares, consolas). Úsala solo cuando el cliente no dio el peso.",
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
                    "producto": {
                        "type": "string",
                        "description": "Nombre corto del producto (ej: 'laptop Lenovo', 'iPhone 15').",
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
            "name": "derivar_a_asesor",
            "description": "Transfiere el chat a un asesor humano y silencia el bot. Úsala solo cuando el cliente pide explícitamente hablar con un asesor, una persona o un humano, o que lo llamen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {
                        "type": "string",
                        "description": "Frase breve con lo que pidió el cliente.",
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

# Ventana de contexto: solo se recuerdan las últimas 12 h de conversación.
HORAS_CONTEXTO = 12
MAX_MENSAJES_CONTEXTO = 40


def get_or_create_history(chat_id: str) -> List[Dict[str, str]]:
    """Reconstruye el historial del LLM desde SQLite en cada turno.

    Así sobrevive a reinicios de Render e incluye lo que escribió el asesor
    desde el dashboard. Se omiten los mensajes finales del cliente que aún no
    tienen respuesta: son los del turno actual y llegan consolidados aparte.
    """
    desde = datetime.now() - timedelta(hours=HORAS_CONTEXTO)
    mensajes = obtener_mensajes_recientes(chat_id, desde, MAX_MENSAJES_CONTEXTO)
    while mensajes and mensajes[-1]["emisor"] == "cliente":
        mensajes.pop()

    history: List[Dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in mensajes:
        texto = m.get("texto") or ""
        emisor = m.get("emisor") or ""
        if emisor == "cliente":
            history.append({"role": "user", "content": texto})
        elif emisor.startswith("bot"):
            history.append({"role": "assistant", "content": texto})
        else:  # mensaje de un asesor humano enviado desde el dashboard
            history.append(
                {"role": "assistant", "content": f"[Mensaje del asesor {emisor}]: {texto}"}
            )

    # Copia del último historial construido (útil para depurar y en pruebas).
    sessions[chat_id] = {"history": history, "last_active": datetime.now()}
    return history


# 📤 ENVÍO DE MENSAJES VÍA META CLOUD API
async def _post_meta(payload: Dict) -> bool:
    """Único punto de salida hacia la Graph API (texto, botones, listas, leído)."""
    if not META_PHONE_NUMBER_ID or not META_ACCESS_TOKEN:
        print("⚠️ [Meta Cloud API] Faltan META_PHONE_NUMBER_ID/META_ACCESS_TOKEN; no se envía.")
        return False
    url = f"https://graph.facebook.com/v21.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as http_client:
        try:
            res = await http_client.post(url, json=payload, headers=headers, timeout=10.0)
            if res.status_code == 200:
                return True
            print(f"⚠️ Error Meta API ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"❌ Error de conexión al enviar con Meta: {e}")
    return False


def _payload_base(to_recipient: str) -> Dict:
    """Destinatario: BSUID (ej. PE.2347...) va en 'recipient'; teléfono E.164 en 'to'."""
    clean_recipient = str(to_recipient).replace("@c.us", "").strip()
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual"}
    if "." in clean_recipient and not clean_recipient.isdigit():
        payload["recipient"] = clean_recipient
    else:
        payload["to"] = clean_recipient
    return payload


async def _enviar(to_recipient: str, contenido: Dict) -> bool:
    """Envía al ID del cliente; si Meta lo rechaza y conocemos su teléfono, reintenta con él."""
    payload = _payload_base(to_recipient)
    payload.update(contenido)
    if await _post_meta(payload):
        return True
    if "recipient" in payload:
        chat = obtener_chat(str(to_recipient)) or {}
        if chat.get("telefono"):
            print(f"↩️ [Meta Cloud API] Reintento por teléfono para [{to_recipient}]")
            respaldo = _payload_base(chat["telefono"])
            respaldo.update(contenido)
            return await _post_meta(respaldo)
    return False


async def send_meta_whatsapp_message(to_recipient: str, message: str):
    """Envía un mensaje de texto."""
    if await _enviar(to_recipient, {"type": "text", "text": {"preview_url": False, "body": message}}):
        print(f"✅ [Meta Cloud API] Mensaje entregado a [{to_recipient}]")


async def send_meta_interactive(to_recipient: str, interactive: Dict):
    """Envía un mensaje interactivo (botones de respuesta o lista)."""
    await _enviar(to_recipient, {"type": "interactive", "interactive": interactive})


async def marcar_leido_y_escribiendo(id_mensaje: str):
    """Marca el mensaje como leído y muestra "escribiendo…" (hasta ~25 s o hasta responder)."""
    if not id_mensaje:
        return
    await _post_meta(
        {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": id_mensaje,
            "typing_indicator": {"type": "text"},
        }
    )


# 🔘 MENÚS INTERACTIVOS (títulos de botón: máx. 20 caracteres; filas de lista: 24)
BOTONES_MENU = [("cotizar", "Cotizar envío"), ("rastrear", "Rastrear paquete"), ("otras", "Otras consultas")]
BOTONES_POST_COTIZACION = [("asesor", "Hablar con asesor"), ("cotizar_otro", "Cotizar otro"), ("como_compro", "¿Cómo compro?")]
BOTONES_RECUPERACION = [("cotizar", "Cotizar envío"), ("rastrear", "Rastrear paquete"), ("asesor", "Hablar con asesor")]
FILAS_OTRAS_CONSULTAS = [
    ("faq_direccion", "Dirección en Miami"),
    ("faq_plazos", "Plazos de entrega"),
    ("faq_provincias", "Envíos a provincias"),
    ("faq_como_funciona", "Cómo funciona"),
    ("faq_pagos", "Formas de pago"),
    ("viajero", "Modalidad viajero"),
    ("asesor", "Hablar con un asesor"),
]
# Lo que "dice" el cliente al tocar cada opción (entra al flujo normal como texto).
TEXTO_POR_OPCION = {
    "cotizar": "Quiero cotizar un envío",
    "cotizar_otro": "Quiero cotizar otro producto",
    "rastrear": "Quiero rastrear un paquete",
    "como_compro": "Quiero saber cómo funciona el proceso para comprar",
    "faq_direccion": "¿Cuál es la dirección del almacén en Miami?",
    "faq_plazos": "¿Cuánto demora el envío?",
    "faq_provincias": "¿Envían a provincias?",
    "faq_como_funciona": "¿Cómo funciona el servicio?",
    "faq_pagos": "¿Cuáles son las formas de pago?",
    "viajero": "Quiero información de la modalidad viajero",
    "asesor": "Quiero hablar con un asesor",
}


def interactivo_botones(cuerpo: str, botones) -> Dict:
    return {
        "type": "button",
        "body": {"text": cuerpo},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": id_, "title": titulo}}
                for id_, titulo in botones
            ]
        },
    }


def interactivo_lista(cuerpo: str, boton: str, filas) -> Dict:
    return {
        "type": "list",
        "body": {"text": cuerpo},
        "action": {
            "button": boton,
            "sections": [
                {"title": "Consultas", "rows": [{"id": id_, "title": t} for id_, t in filas]}
            ],
        },
    }


def texto_para_registro(cuerpo: str, opciones) -> str:
    """Cómo queda el mensaje interactivo en la BD (dashboard e historial del LLM)."""
    return f"{cuerpo}\n[Opciones: {' | '.join(t for _, t in opciones)}]"


async def enviar_y_registrar_menu(chat_id: str, cuerpo: str, botones):
    registrar_mensaje_saliente(chat_id, "bot", texto_para_registro(cuerpo, botones), None)
    await send_meta_interactive(chat_id, interactivo_botones(cuerpo, botones))


async def enviar_lista_otras_consultas(chat_id: str):
    cuerpo = "Elige el tema de tu consulta:"
    registrar_mensaje_saliente(
        chat_id, "bot", texto_para_registro(cuerpo, FILAS_OTRAS_CONSULTAS), None
    )
    await send_meta_interactive(
        chat_id, interactivo_lista(cuerpo, "Ver opciones", FILAS_OTRAS_CONSULTAS)
    )


# 🆔 IDENTIFICACIÓN DEL CLIENTE
def _es_bsuid(valor: str) -> bool:
    """BSUID de Meta: código de país + punto + alfanumérico (ej. 'PE.2347...')."""
    return bool(valor) and "." in valor and not valor.replace("+", "").isdigit()


def identificar_cliente(msg: Dict, contacts: List[Dict]):
    """Devuelve (chat_id, telefono).

    chat_id es siempre el BSUID si Meta lo envía (está disponible aunque el
    cliente oculte su número); si no llega (payloads antiguos), se usa el
    teléfono. telefono es None cuando el cliente lo tiene oculto.
    """
    contacto = contacts[0] if contacts else {}
    candidatos_id = [
        contacto.get("user_id"),
        msg.get("from_user_id"),
        msg.get("user_id"),
        msg.get("from") if _es_bsuid(str(msg.get("from") or "")) else None,
        contacto.get("wa_id") if _es_bsuid(str(contacto.get("wa_id") or "")) else None,
    ]
    bsuid = next((str(c).strip() for c in candidatos_id if c), None)

    candidatos_tel = [msg.get("from"), contacto.get("wa_id")]
    telefono = next(
        (str(t).strip() for t in candidatos_tel if t and str(t).strip().lstrip("+").isdigit()),
        None,
    )
    return (bsuid or telefono), telefono


# 👤 NOMBRE DEL CLIENTE (perfil de WhatsApp)
_NOMBRE_VALIDO = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,20}$")


def nombre_de_pila(nombre_perfil: str) -> Optional[str]:
    """Primer nombre del perfil si parece un nombre real; None si es apodo, emoji, etc."""
    if not nombre_perfil:
        return None
    partes = nombre_perfil.strip().split()
    if not partes or not _NOMBRE_VALIDO.match(partes[0]):
        return None
    nombre = partes[0]
    if nombre.lower() in {"cliente", "user", "usuario", "whatsapp"}:
        return None
    return nombre.capitalize()


def texto_bienvenida(nombre: Optional[str], primer_contacto: bool) -> str:
    if not primer_contacto:
        return "¿En qué más te ayudo?"
    saludo = f"¡Hola, {nombre}! 👋" if nombre else "¡Hola! 👋"
    return (
        f"{saludo} Soy *Globix, el asistente virtual de Globex Courier*. Te ayudo a cotizar tus compras "
        "en EE. UU. y a resolver tus dudas al instante. Si prefieres hablar con una persona, solo dímelo.\n\n"
        "¿En qué te ayudo?\n\n"
        '_También puedes escribirme directamente, por ejemplo: "iPhone 15 de $900"._'
    )


def texto_derivacion(nombre: Optional[str]) -> str:
    inicio = f"Listo, {nombre}." if nombre else "Listo."
    return (
        f"{inicio} Le pasé tu consulta a un asesor de Globex y te escribirá por este chat "
        "lo antes posible. Ya tiene el detalle de tu consulta, así que no necesitas repetir nada. 🙌"
    )


PREGUNTA_NOMBRE = "Mientras tanto, ¿me compartes tu nombre completo para que tu asesor te atienda?"


def pedir_nombre_si_falta(chat_id: str) -> str:
    """Al derivar: si aún no tenemos el nombre del cliente, lo pedimos (una vez).

    Devuelve el texto a agregar al mensaje de derivación ("" si no hace falta).
    """
    chat = obtener_chat(chat_id) or {}
    if chat.get("nombre_cliente") or chat.get("esperando_nombre"):
        return ""
    marcar_esperando_nombre(chat_id, True)
    return "\n\n" + PREGUNTA_NOMBRE


def nombre_para_saludo(chat_id: str, nombre_perfil: str) -> Optional[str]:
    """Primer nombre: el que dio el cliente si existe; si no, el del perfil."""
    chat = obtener_chat(chat_id) or {}
    if chat.get("nombre_cliente"):
        return chat["nombre_cliente"].split()[0]
    return nombre_de_pila(nombre_perfil)


RESPUESTA_ERROR = "Disculpa, tuve un inconveniente interno al procesar tu consulta. ¿Podrías repetirla?"
TEXTO_RECUPERACION = "Disculpa, no logré entenderte 😅. Elige una opción o pide hablar con un asesor:"
TEXTO_FUERA_DE_ALCANCE = (
    "Eso está fuera de lo que puedo ayudarte 😊. Soy Globix y te ayudo con tus importaciones "
    "de EE. UU. a Perú con Globex Courier. ¿Qué deseas hacer?"
)
# Meta limita el cuerpo de un mensaje interactivo a 1024 caracteres.
LIMITE_CUERPO_INTERACTIVO = 1000
# Máximo de llamadas al LLM por mensaje del cliente (evita bucles de herramientas).
MAX_RONDAS_HERRAMIENTAS = 3


def ejecutar_herramienta(
    nombre_funcion: str,
    argumentos_json: str,
    chat_id: str,
    texto_consolidado: str,
    textos_cliente: List[str],
    estado: Dict,
):
    """Ejecuta una herramienta pedida por el LLM.

    Devuelve (resultado_para_llm, respuesta_final). Si respuesta_final no es None,
    ese texto (armado por código) es lo que se envía al cliente; si es None, el
    resultado vuelve al LLM para que continúe la conversación.
    """
    try:
        args = json.loads(argumentos_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("los argumentos no son un objeto")
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"Argumentos inválidos: {e}"}, None

    # RAG DE PESOS: el resultado vuelve al LLM para que pida o calcule
    if nombre_funcion == "consultar_peso_producto":
        info_prod = buscar_peso_producto(str(args.get("nombre_producto", "")))
        if info_prod and info_prod.get("peso_kg"):
            estado["pesos_referenciales"].append(float(info_prod["peso_kg"]))
        return (info_prod if info_prod else {"encontrado": False}), None

    # CÁLCULO DETERMINISTA COURIER (argumentos validados en código)
    if nombre_funcion == "calcular_cotizacion":
        if estado["resultado_calculo"] is not None:
            return {"error": "Ya se emitió una cotización en este mensaje."}, None
        validacion = validar_argumentos_cotizacion(
            args, textos_cliente, estado["pesos_referenciales"]
        )
        if isinstance(validacion, str):
            print(f"🚫 [Validación] Cotización rechazada para [{chat_id}]: {validacion}")
            return {"error": validacion}, None
        val, peso = validacion
        if GlobexPricingEngine.requiere_asesor(val):
            print(f"💼 [Tope USD 1 200] Valor {val} supera el cálculo automático en [{chat_id}]")
            actualizar_clasificacion_chat(
                chat_id, servicio="Cotización Courier (alto valor)", estado="Listo para Asesor", paso=4
            )
            actualizar_estado_chat(chat_id, nuevo_estado="Listo para Asesor", bot_activo=0)
            return {"derivado": True}, (
                f"Por el valor de tu compra (más de USD {GlobexPricingEngine.LIMITE_COTIZACION_AUTOMATICA:,.0f}), "
                "un asesor de Globex preparará tu cotización personalizada y te escribirá por este chat a la brevedad."
            ) + pedir_nombre_si_falta(chat_id)
        resultado = GlobexPricingEngine.calcular(val, peso)
        estado["resultado_calculo"] = resultado
        actualizar_clasificacion_chat(chat_id, servicio="Cotización Courier", paso=3)
        # Confirmación de lo entendido, en el mismo mensaje de la cotización
        peso_de_catalogo = any(abs(peso - p) < 1e-9 for p in estado["pesos_referenciales"])
        partes = []
        producto = str(args.get("producto") or "").strip()[:40]
        if producto:
            partes.append(producto)
        partes.append(f"USD {val:,.2f}".replace(".00", ""))
        partes.append(f"~{peso:g} kg (peso estimado con caja)" if peso_de_catalogo else f"{peso:g} kg")
        respuesta = (
            f"Entendí: *{', '.join(partes)}* 👇\n\n"
            + GlobexPricingEngine.formatear_mensaje_whatsapp(resultado)
        )
        estado["menu"] = BOTONES_POST_COTIZACION
        return {"cotizacion_emitida": True}, respuesta

    # FUERA DE ALCANCE (texto fijo + botones; el LLM no responde el tema ajeno)
    if nombre_funcion == "fuera_de_alcance":
        print(f"🚧 [Alcance] Tema ajeno en [{chat_id}]: {args.get('tema', '')}")
        estado["menu"] = BOTONES_MENU
        return {"redirigido": True}, TEXTO_FUERA_DE_ALCANCE

    # BIENVENIDA / MENÚ DE OPCIONES (texto fijo + botones)
    if nombre_funcion == "mostrar_menu":
        estado["menu"] = BOTONES_MENU
        return {"menu_mostrado": True}, texto_bienvenida(
            estado.get("nombre"), estado.get("primer_contacto", False)
        )

    # BASE DE CONOCIMIENTO (FAQs)
    if nombre_funcion == "consultar_faq_comercial":
        info_faq = buscar_faq_comercial(texto_consolidado) or buscar_faq_comercial(
            str(args.get("tema", ""))
        )
        respuesta = (
            info_faq["contenido"]
            if info_faq
            else "Globex realiza envíos de USA a Perú en 5 a 7 días hábiles. ¿Deseas cotizar algún producto?"
        )
        return {"respondido": True}, respuesta

    # SEGUIMIENTO
    if nombre_funcion == "clasificar_como_seguimiento":
        actualizar_clasificacion_chat(
            chat_id, servicio="Seguimiento Courier", estado="Listo para Asesor", paso=4
        )
        actualizar_estado_chat(chat_id, nuevo_estado="Listo para Asesor", bot_activo=0)
        return {"derivado": True}, (
            "📦 He registrado tu consulta de seguimiento. Tu asesor asignado revisará "
            "el estado de tu paquete en almacén y te responderá a la brevedad por aquí."
        ) + pedir_nombre_si_falta(chat_id)

    # VIAJERO
    if nombre_funcion == "clasificar_como_viajero":
        actualizar_clasificacion_chat(
            chat_id, servicio="Cotización Viajero", estado="Listo para Asesor", paso=4
        )
        actualizar_estado_chat(chat_id, nuevo_estado="Listo para Asesor", bot_activo=0)
        return {"derivado": True}, (
            "🧳 La modalidad de *Viajero* depende del cupo y fecha de vuelos programados. "
            "He transferido tu solicitud a nuestro asesor especializado para confirmarte disponibilidad."
        ) + pedir_nombre_si_falta(chat_id)

    # ESCAPE A ATENCIÓN HUMANA (lo decide el LLM según la intención del cliente)
    if nombre_funcion == "derivar_a_asesor":
        print(
            f"👨‍💼 [Escape Hatch] Cliente [{chat_id}] solicitó atención humana "
            f"(motivo: {args.get('motivo', '')})."
        )
        actualizar_estado_chat(chat_id, nuevo_estado="Listo para Asesor", bot_activo=0)
        return {"derivado": True}, texto_derivacion(estado.get("nombre")) + pedir_nombre_si_falta(chat_id)

    print(f"⚠️ [Tool Calling] Herramienta desconocida: {nombre_funcion}")
    return {"error": f"La herramienta '{nombre_funcion}' no existe."}, None


async def procesar_mensaje_consolidado(
    chat_id: str, sender_name: str, texto_consolidado: str
):
    print(f"\n🚀 Procesando consolidado de [{chat_id}]: '{texto_consolidado}'")

    # 🛑 El escape a atención humana (T13 / F42) lo decide el LLM con la
    # herramienta 'derivar_a_asesor', según la intención y no por palabras sueltas.

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
            bot_reply += pedir_nombre_si_falta(chat_id)

        registrar_mensaje_saliente(chat_id, "bot", bot_reply, None)
        await send_meta_whatsapp_message(chat_id, bot_reply)
        return

    # 💬 3. CONVERSACIÓN Y LLAMADA A HERRAMIENTAS (TOOL CALLING)
    history = get_or_create_history(chat_id)
    history.append({"role": "user", "content": texto_consolidado})

    inicio_turno = len(history)
    nombre = nombre_para_saludo(chat_id, sender_name)
    if nombre:
        history[0] = {
            "role": "system",
            "content": SYSTEM_PROMPT + f"\n\nEl cliente se llama {nombre}.",
        }
    previas_del_bot = [m["content"] for m in history[:-1] if m.get("role") == "assistant"]
    estado = {
        "resultado_calculo": None,
        "pesos_referenciales": [],
        "nombre": nombre,
        "primer_contacto": not previas_del_bot,
        "menu": None,
    }
    textos_cliente = [
        m["content"]
        for m in history
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    ]

    try:
        bot_reply = None
        respuestas_finales: List[str] = []

        for _ in range(MAX_RONDAS_HERRAMIENTAS):
            ai_response = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=history,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            response_message = ai_response.choices[0].message

            if not response_message.tool_calls:
                bot_reply = limpiar_respuesta_llm(response_message.content)
                # Capa 2: revisión determinista de la respuesta libre antes de enviarla
                motivo = revisar_respuesta_libre(bot_reply, textos_cliente)
                if motivo:
                    print(f"🛑 [Revisión de salida] Respuesta bloqueada en [{chat_id}] ({motivo}): {bot_reply!r}")
                    bot_reply = TEXTO_FUERA_DE_ALCANCE
                    estado["menu"] = BOTONES_MENU
                break

            # Se registran TODAS las llamadas y cada una recibe su respuesta "tool",
            # como exige la API para que el historial siga siendo válido.
            history.append(
                {
                    "role": "assistant",
                    "content": response_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in response_message.tool_calls
                    ],
                }
            )
            for tool_call in response_message.tool_calls:
                resultado_para_llm, respuesta_final = ejecutar_herramienta(
                    tool_call.function.name,
                    tool_call.function.arguments,
                    chat_id,
                    texto_consolidado,
                    textos_cliente,
                    estado,
                )
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": json.dumps(resultado_para_llm, ensure_ascii=False),
                    }
                )
                if respuesta_final:
                    respuestas_finales.append(respuesta_final)

            # Cotización, FAQ o derivación: la respuesta la arma el código, no el LLM.
            if respuestas_finales:
                bot_reply = "\n\n".join(respuestas_finales)
                break

        if not bot_reply:
            bot_reply = RESPUESTA_ERROR
        history.append({"role": "assistant", "content": bot_reply})
        resultado_calculo = estado["resultado_calculo"]

    except Exception as e:
        print(f"❌ Error al procesar mensaje: {e}")
        # Deshace mensajes de herramientas a medias: un tool_call sin respuesta
        # rompería todas las llamadas siguientes de este chat.
        del history[inicio_turno:]
        resultado_calculo = None
        estado["menu"] = None
        bot_reply = RESPUESTA_ERROR
        history.append({"role": "assistant", "content": bot_reply})

    # 🔁 Dos fallos seguidos: en vez de repetir el error, ofrecer opciones y asesor
    if (
        bot_reply == RESPUESTA_ERROR
        and previas_del_bot
        and previas_del_bot[-1].startswith(RESPUESTA_ERROR)
    ):
        bot_reply = TEXTO_RECUPERACION
        estado["menu"] = BOTONES_RECUPERACION

    # 📄 GENERAR PROFORMA PDF SI HUBO COTIZACIÓN
    if resultado_calculo:
        try:
            chat_pdf = obtener_chat(chat_id) or {}
            ruta_pdf = generar_pdf_cotizacion(
                chat_id, chat_pdf.get("nombre_cliente") or sender_name, resultado_calculo
            )
            print(f"📄 [PDF Generado exitosamente]: {ruta_pdf}")
            bot_reply += "\n\n📄 *He emitido tu Proforma Oficial en PDF.* Tu asesor te la puede compartir en cualquier momento."
        except Exception as e:
            print(f"Error generando PDF: {e}")

    # Botones solo si el bot sigue atendiendo (si derivó, el asesor toma el control)
    menu = estado["menu"] if esta_bot_activo(chat_id) else None

    if not menu:
        registrar_mensaje_saliente(chat_id, "bot", bot_reply, resultado_calculo)
        await send_meta_whatsapp_message(chat_id, bot_reply)
    elif len(bot_reply) <= LIMITE_CUERPO_INTERACTIVO:
        registrar_mensaje_saliente(
            chat_id, "bot", texto_para_registro(bot_reply, menu), resultado_calculo
        )
        await send_meta_interactive(chat_id, interactivo_botones(bot_reply, menu))
    else:
        # Texto largo: va como mensaje normal y los botones en uno corto aparte
        registrar_mensaje_saliente(chat_id, "bot", bot_reply, resultado_calculo)
        await send_meta_whatsapp_message(chat_id, bot_reply)
        await enviar_y_registrar_menu(chat_id, "¿Qué deseas hacer ahora?", menu)


_tareas_fondo: set = set()


def _en_segundo_plano(corrutina):
    """Lanza una tarea sin bloquear y guarda la referencia para que no se pierda."""
    tarea = asyncio.create_task(corrutina)
    _tareas_fondo.add(tarea)
    tarea.add_done_callback(_tareas_fondo.discard)
    return tarea


async def derivar_a_asesor(chat_id: str, sender_name: str):
    """Derivación directa (botón 'Hablar con asesor'): silencia el bot y avisa al cliente."""
    actualizar_estado_chat(chat_id, nuevo_estado="Listo para Asesor", bot_activo=0)
    respuesta = texto_derivacion(nombre_para_saludo(chat_id, sender_name)) + pedir_nombre_si_falta(chat_id)
    registrar_mensaje_saliente(chat_id, "bot", respuesta, None)
    await send_meta_whatsapp_message(chat_id, respuesta)


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

    if (
        META_VERIFY_TOKEN
        and mode == "subscribe"
        and token
        and hmac.compare_digest(token, META_VERIFY_TOKEN)
    ):
        print("✅ [Meta Webhook] Handshake verificado exitosamente.")
        return Response(content=challenge, media_type="text/plain")
    return Response(
        content="Token de verificación inválido", status_code=403
    )


# 🌐 2. ENDPOINT POST: RECEPCIÓN OFICIAL DE MENSAJES DE META (CON FILTRO DE FANTASMAS)
@app.post("/meta-webhook")
async def meta_webhook(request: Request, background_tasks: BackgroundTasks):
    """Endpoint oficial que recibe y procesa todos los eventos de WhatsApp Cloud API."""
    cuerpo = await request.body()
    if not firma_meta_valida(
        cuerpo, request.headers.get("X-Hub-Signature-256", "")
    ):
        print("🚫 [Meta Webhook] Firma X-Hub-Signature-256 inválida o ausente.")
        return Response(content="Firma inválida", status_code=403)
    data = json.loads(cuerpo)

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        # Si es solo un acuse de recibo de Meta (sent/delivered/read), lo ignoramos
        if not messages:
            return {"status": "event_without_messages"}

        msg = messages[0]
        msg_type = msg.get("type")
        id_message = msg.get("id")
        msg_timestamp = msg.get(
            "timestamp"
        )  # Marca de tiempo original de WhatsApp

        # ⏰ 1. MENSAJES ATRASADOS: se responden igual (un cliente sin respuesta
        # es peor que una respuesta tardía). Solo se registra la demora en el log;
        # los reintentos repetidos los frena la deduplicación por wamid.
        if msg_timestamp:
            try:
                segundos_antiguedad = time.time() - float(msg_timestamp)
            except (TypeError, ValueError):
                segundos_antiguedad = 0
            if segundos_antiguedad > 600:
                print(
                    f"⏰ [Mensaje Atrasado] [{id_message}] llegó con {segundos_antiguedad/60:.1f} min de demora. Se responde igual."
                )

        # 🛡️ 2. PASO HP01: DEDUPLICACIÓN DE MENSAJES POR ID (Regla T28 del Manual)
        if id_message and es_mensaje_duplicado(id_message):
            print(
                f"⚠️ [Deduplicación HP01] Mensaje Meta [{id_message}] ya procesado."
            )
            return {"status": "duplicate_ignored"}

        # 3. Nombre del cliente provisto por Meta
        contacts = value.get("contacts", [])
        sender_name = (
            contacts[0].get("profile", {}).get("name", "Cliente")
            if contacts
            else "Cliente"
        )

        # 4. Identificador único: siempre el ID de usuario de Meta (BSUID); el
        # teléfono solo se guarda como respaldo de envío cuando Meta lo comparte.
        chat_id, telefono = identificar_cliente(msg, contacts)

        if not chat_id or chat_id == "None":
            print(
                f"⚠️ [Meta Webhook] No se pudo extraer un ID para {sender_name}. Payload: {msg}"
            )
            return {"status": "missing_recipient_id"}

        # 🖼️🎙️ 5. TRATAMIENTO DE NO-TEXTUALES (Audios, Fotos, Documentos - OBS01 / T11)
        if msg_type in ["image", "audio", "document", "video"]:
            tipo_adjunto = (
                "audio 🎙️"
                if msg_type == "audio"
                else "imagen 📷"
                if msg_type == "image"
                else "documento 📄"
            )
            print(
                f"\n📎 Archivo no textual ({msg_type}) recibido de [{chat_id}] ({sender_name})"
            )

            registrar_mensaje_entrante(
                chat_id,
                sender_name,
                f"[{tipo_adjunto.upper()} ADJUNTO]",
                id_mensaje=id_message,
            )
            if telefono:
                guardar_telefono(chat_id, telefono)

            if not esta_bot_activo(chat_id):
                return {"status": "bot_silenced_for_human"}

            bot_reply = (
                f"He recibido tu {tipo_adjunto}. Por el momento atiendo consultas por texto.\n\n"
                f"¿Podrías escribir brevemente tu consulta o describir el producto para ayudarte con tu cotización?"
            )
            registrar_mensaje_saliente(chat_id, "bot", bot_reply, None)
            await send_meta_whatsapp_message(chat_id, bot_reply)
            return {"status": "media_handled"}

        # 🔘 TOQUE DE BOTÓN O FILA DE LISTA: se traduce a lo que "dijo" el cliente
        opcion_elegida = None
        if msg_type == "interactive":
            interactivo = msg.get("interactive", {})
            respuesta = interactivo.get("button_reply") or interactivo.get("list_reply") or {}
            opcion_elegida = respuesta.get("id")
            texto_opcion = TEXTO_POR_OPCION.get(opcion_elegida) or respuesta.get("title", "")
            if not texto_opcion:
                return {"status": "interactive_without_option"}
            msg_type = "text"
            msg = {**msg, "text": {"body": texto_opcion}}

        # 💬 6. TRATAMIENTO DE MENSAJES DE TEXTO ESTÁNDAR
        if msg_type == "text":
            user_text = msg.get("text", {}).get("body", "").strip()
            print(
                f"\n📩 [Meta] Mensaje de {sender_name} [{chat_id}]: {user_text}"
            )

            registrar_mensaje_entrante(
                chat_id, sender_name, user_text, id_mensaje=id_message
            )
            if telefono:
                guardar_telefono(chat_id, telefono)

            # 👤 Respuesta a "¿me compartes tu nombre?" (se pidió al derivar).
            # Se intenta una sola vez; si no parece un nombre, lo ve el asesor.
            chat_info = obtener_chat(chat_id) or {}
            if chat_info.get("esperando_nombre") and not opcion_elegida:
                marcar_esperando_nombre(chat_id, False)
                nombre_dado = extraer_nombre(user_text)
                if nombre_dado:
                    guardar_nombre_cliente(chat_id, nombre_dado)
                    gracias = f"¡Gracias, {nombre_dado.split()[0]}! Ya se lo pasé a tu asesor. 🙌"
                    registrar_mensaje_saliente(chat_id, "bot", gracias, None)
                    await send_meta_whatsapp_message(chat_id, gracias)
                    return {"status": "name_saved"}

            # Silencio si el asesor humano tiene el control
            if not esta_bot_activo(chat_id):
                print(
                    f"🤫 [Bot Silenciado] El chat [{chat_id}] está bajo atención humana."
                )
                return {"status": "bot_silenced_for_human"}

            # "Leído" + "escribiendo…" mientras se arma la respuesta
            _en_segundo_plano(marcar_leido_y_escribiendo(id_message))

            # Opciones que no necesitan al LLM: se responden al instante
            if opcion_elegida == "otras":
                await enviar_lista_otras_consultas(chat_id)
                return {"status": "list_sent"}
            if opcion_elegida == "asesor":
                await derivar_a_asesor(chat_id, sender_name)
                return {"status": "derived_to_advisor"}

            # Acumular en buffer para Debouncing de 5 segundos
            if chat_id not in message_buffer:
                message_buffer[chat_id] = []
            message_buffer[chat_id].append(user_text)

            # Ventana deslizante: si entra otro mensaje dentro de los 5s, se reinicia el reloj
            if chat_id in buffer_tasks and not buffer_tasks[chat_id].done():
                buffer_tasks[chat_id].cancel()

            buffer_tasks[chat_id] = asyncio.create_task(
                debounce_mensajes(chat_id, sender_name)
            )

    except Exception as e:
        print(f"Error procesando webhook de Meta: {e}")

    # Retorna 200 OK a Meta inmediatamente para evitar reintentos automáticos
    return {"status": "received_ok"}


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
    if not META_WABA_ID or not META_ACCESS_TOKEN:
        print("⚠️ [Meta WABA Sync] Sin META_WABA_ID/META_ACCESS_TOKEN; se omite la suscripción.")
        return
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


@app.get("/api/chats", dependencies=[Depends(verificar_api_key)])
def api_obtener_chats():
    """Devuelve la lista completa de chats y sus estados para el Dashboard."""
    return obtener_todos_los_chats()


@app.get("/api/messages/{chat_id}", dependencies=[Depends(verificar_api_key)])
def api_obtener_mensajes(chat_id: str):
    """Devuelve el historial de mensajes de un chat específico."""
    return obtener_mensajes_chat(chat_id)


@app.post("/api/send-advisor-message", dependencies=[Depends(verificar_api_key)])
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


@app.post("/api/update-chat-status", dependencies=[Depends(verificar_api_key)])
def api_actualizar_estado(payload: ActualizarEstadoPayload):
    """Permite al asesor cambiar el estado de un lead o reactivar el bot."""
    actualizar_estado_chat(
        payload.chat_id,
        payload.nuevo_estado,
        payload.nuevo_asesor,
        payload.bot_activo,
    )
    return {"status": "updated"}


@app.get("/api/download-pdf/{chat_id}", dependencies=[Depends(verificar_api_key)])
def api_descargar_pdf(chat_id: str):
    """Permite al asesor descargar el PDF oficial generado en el servidor."""
    ruta_pdf = buscar_ultimo_pdf(chat_id)
    if ruta_pdf:
        return FileResponse(
            ruta_pdf,
            media_type="application/pdf",
            filename=os.path.basename(ruta_pdf),
        )
    return Response(content="PDF no encontrado", status_code=404)


@app.post("/api/admin/clean-data", dependencies=[Depends(verificar_api_key)])
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