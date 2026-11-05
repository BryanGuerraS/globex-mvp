"""Resumen del caso para el asesor cuando Globix deriva.

Se arma con datos del sistema (no con el LLM): así no suma demora ni costo y
no puede inventar nada. Incluye el motivo, el cliente, la última cotización
(producto, precio, peso y total, tomados de la llamada al motor) y los últimos
mensajes del cliente.
"""

import json
from typing import Dict, List, Optional

from database import obtener_chat, obtener_mensajes_chat, obtener_metricas_chat

MOTIVOS = {
    "asesor": "Pidió hablar con un asesor",
    "tope": "Compra de más de USD 1,200 (cotización personalizada)",
    "seguimiento": "Consulta de seguimiento de paquete",
    "viajero": "Consulta por modalidad viajero",
    "restringido": "Mercancía restringida: revisar requisitos antes de cotizar",
}
ULTIMOS_MENSAJES = 3


def _ultima_cotizacion(chat_id: str) -> Optional[Dict]:
    """Argumentos de la última llamada a calcular_cotizacion (producto, valor, peso)."""
    for fila in reversed(obtener_metricas_chat(chat_id)):
        for herramienta in reversed(json.loads(fila.get("herramientas") or "[]")):
            if herramienta.get("nombre") == "calcular_cotizacion":
                try:
                    return json.loads(herramienta.get("argumentos") or "{}")
                except json.JSONDecodeError:
                    return None
    return None


def _ultimos_mensajes_cliente(chat_id: str, n: int = ULTIMOS_MENSAJES) -> List[str]:
    mensajes = [m["texto"] for m in obtener_mensajes_chat(chat_id) if m.get("emisor") == "cliente"]
    return mensajes[-n:]


def construir_resumen(chat_id: str, motivo: Optional[str], detalle: str = "") -> str:
    """Texto del resumen (formato WhatsApp/Telegram: *negrita*)."""
    chat = obtener_chat(chat_id) or {}
    nombre = chat.get("nombre_cliente") or "Aún no dio su nombre"
    lineas = [
        f"*Motivo:* {MOTIVOS.get(motivo, motivo or 'Derivación')}" + (f" ({detalle})" if detalle else ""),
        f"*Cliente:* {nombre} · ID {chat_id}",
        f"*Servicio:* {chat.get('servicio') or '—'}",
    ]

    cotizacion = _ultima_cotizacion(chat_id)
    if cotizacion or chat.get("cotizacion_total"):
        partes = []
        if cotizacion:
            if cotizacion.get("producto"):
                partes.append(str(cotizacion["producto"]))
            if cotizacion.get("valor_producto_usd") is not None:
                partes.append(f"USD {float(cotizacion['valor_producto_usd']):,.2f}")
            if cotizacion.get("peso_kg") is not None:
                partes.append(f"{float(cotizacion['peso_kg']):g} kg")
        if chat.get("cotizacion_total"):
            partes.append(f"total USD {chat['cotizacion_total']:,.2f}")
        lineas.append(f"*Cotización:* {', '.join(partes)}")

    mensajes = _ultimos_mensajes_cliente(chat_id)
    if mensajes:
        lineas.append("*Últimos mensajes del cliente:*")
        lineas += [f"• {m[:200]}" for m in mensajes]
    return "\n".join(lineas)
