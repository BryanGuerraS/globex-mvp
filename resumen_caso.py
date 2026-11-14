"""Resumen del caso para el asesor cuando Globix deriva.

Se arma con datos del sistema (no con el LLM): así no suma demora ni costo y
no puede inventar nada. Incluye el motivo, el cliente, la última cotización
(producto, precio, peso y total, tomados de la llamada al motor) y los últimos
mensajes del cliente.
"""

import json
import re
from typing import Dict, List, Optional

from database import obtener_chat, obtener_mensajes_chat, obtener_metricas_chat
from pricing_engine import GlobexPricingEngine

_TOPE = f"USD {GlobexPricingEngine.LIMITE_COTIZACION_AUTOMATICA:,.0f}"

MOTIVOS = {
    "asesor": "Pidió hablar con un asesor",
    "tope": f"Compra de más de {_TOPE} (cotización personalizada)",
    "seguimiento": "Consulta de seguimiento de paquete",
    "viajero": "Consulta por modalidad viajero",
    "restringido": "Mercancía restringida: revisar requisitos antes de cotizar",
    "consulta": "Consulta que requiere revisión del asesor",
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


# Campos que pide el bloque 5 del E3: motivo, necesidad, datos disponibles y pendientes
CAMPOS_E3 = {"motivo": "*Motivo:*", "necesidad": "*Necesidad:*", "datos": "*Cliente:*", "pendientes": "*Pendientes:*"}
_TRACKING = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{10,}(?![A-Za-z0-9])")


def _necesidad(motivo: Optional[str], producto: str, servicio: str, detalle: str = "") -> str:
    """Qué quiere el lead, en una frase, a partir del motivo y de lo que ya se sabe."""
    if motivo == "tope":
        return f"Cotizar {producto or 'una compra'} por encima del límite automático"
    if motivo == "restringido":
        return f"Importar {producto or 'un producto'} con restricciones de aduana"
    if motivo == "seguimiento":
        return "Saber el estado de su paquete"
    if motivo == "viajero":
        return "Cotizar por la modalidad viajero"
    if motivo == "consulta" and detalle:
        return f"Resolver su consulta sobre {detalle.lower()}"
    if producto:
        return f"Continuar con la cotización de {producto}"
    if servicio and servicio != "—":
        return f"Atención personalizada sobre: {servicio}"
    return "Atención personalizada (ver los últimos mensajes)"


def _pendientes(motivo: Optional[str], detalle: str, chat: Dict, cotizacion: Optional[Dict],
                mensajes: List[str]) -> List[str]:
    """Lo que el asesor tiene que conseguir o hacer para continuar (máximo 3)."""
    pendientes = []
    detalle_bajo = (detalle or "").lower()
    if motivo == "tope":
        pendientes.append("Preparar la cotización personalizada")
    elif motivo == "restringido":
        if "receta" in detalle_bajo:
            pendientes.append("Confirmar que tiene receta médica visada")
        elif "dni" in detalle_bajo or "máximo" in detalle_bajo:
            pendientes.append("Revisar las cantidades frente al máximo por DNI")
        elif "iata" in detalle_bajo:
            pendientes.append("Confirmar si el producto puede viajar en avión")
        else:
            pendientes.append("Revisar los requisitos de importación del producto")
    elif motivo == "seguimiento":
        codigo = next((m.group(0) for t in mensajes for m in [_TRACKING.search(t)] if m), None)
        pendientes.append(f"Ubicar el paquete con el código {codigo}" if codigo else "Pedir el código de tracking")
    elif motivo == "viajero":
        pendientes.append("Pedir productos, cantidades y fechas del viaje")
    elif motivo == "consulta":
        pendientes.append("Revisar el caso concreto: Globix ya le dio la respuesta general")
    elif cotizacion:
        pendientes.append("Validar la cotización y enviar el PDF formal")
    else:
        pendientes.append("Entender la consulta y responder")
    if not chat.get("nombre_cliente"):
        pendientes.append("Nombre del cliente (Globix ya se lo pidió)")
    return pendientes[:3]


def campos_faltantes(resumen: Optional[str]) -> List[str]:
    """Campos del E3 que faltan o vienen vacíos en un resumen (lista vacía = completo)."""
    lineas = (resumen or "").splitlines()
    faltan = []
    for campo, rotulo in CAMPOS_E3.items():
        linea = next((l for l in lineas if l.startswith(rotulo)), None)
        if linea is None or not linea[len(rotulo):].strip(" —"):
            faltan.append(campo)
    return faltan


def _productos_de(cotizacion: Optional[Dict]) -> List[Dict]:
    """Productos de la última llamada al motor: la lista `productos` o el formato de un producto."""
    if not cotizacion:
        return []
    brutos = cotizacion.get("productos") or [{
        "producto": cotizacion.get("producto"), "precio_unitario_usd": cotizacion.get("valor_producto_usd"),
        "cantidad": cotizacion.get("cantidad"), "peso_kg": cotizacion.get("peso_kg")}]
    salida = []
    for b in brutos if isinstance(brutos, list) else []:
        if not isinstance(b, dict):
            continue
        precio = b.get("precio_unitario_usd", b.get("valor_producto_usd"))
        salida.append({"producto": str(b.get("producto") or "").strip(), "tienda": str(b.get("tienda") or "").strip(),
                       "precio": float(precio) if precio is not None else None,
                       "cantidad": int(b.get("cantidad") or 1),
                       "peso": float(b["peso_kg"]) if b.get("peso_kg") is not None else None})
    return salida


def construir_resumen(chat_id: str, motivo: Optional[str], detalle: str = "") -> str:
    """Texto del resumen (formato WhatsApp: *negrita*), tal como lo ve el asesor en la consola."""
    chat = obtener_chat(chat_id) or {}
    nombre = chat.get("nombre_cliente") or "Aún no dio su nombre"
    cotizacion = _ultima_cotizacion(chat_id)
    mensajes = _ultimos_mensajes_cliente(chat_id)
    items = _productos_de(cotizacion)
    producto = ", ".join(i["producto"] for i in items if i["producto"])
    servicio = chat.get("servicio") or "—"
    lineas = [
        f"*Motivo:* {MOTIVOS.get(motivo, motivo or 'Derivación')}" + (f" ({detalle})" if detalle else ""),
        f"*Necesidad:* {_necesidad(motivo, producto, servicio, detalle)}",
        f"*Cliente:* {nombre} · ID {chat_id}",
        f"*Servicio:* {servicio}",
    ]

    if cotizacion or chat.get("cotizacion_total"):
        partes = []
        for item in items:  # productos, cantidades y tiendas del pedido
            texto = item["producto"] or "Producto"
            if item["tienda"]:
                texto += f" ({item['tienda']})"
            if item["precio"] is not None:
                precio = f"USD {item['precio']:,.2f}"
                texto += f" {item['cantidad']} × {precio}" if item["cantidad"] > 1 else f" {precio}"
            if item["peso"] is not None:
                texto += f", {item['peso']:g} kg"
            partes.append(texto)
        if cotizacion and cotizacion.get("peso_total_kg") is not None:
            partes.append(f"peso total {float(cotizacion['peso_total_kg']):g} kg")
        if chat.get("cotizacion_total"):
            partes.append(f"total USD {chat['cotizacion_total']:,.2f}")
        lineas.append(f"*Cotización:* {', '.join(partes)}")

    lineas.append("*Pendientes:* " + "; ".join(_pendientes(motivo, detalle, chat, cotizacion, mensajes)))
    if mensajes:
        lineas.append("*Últimos mensajes del cliente:*")
        lineas += [f"• {m[:200]}" for m in mensajes]
    return "\n".join(lineas)
