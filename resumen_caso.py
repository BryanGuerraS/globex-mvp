"""Resumen del caso para el asesor cuando Globix deriva.

Se arma con datos del sistema (no con el LLM): así no suma demora ni costo y
no puede inventar nada. Incluye el motivo, el cliente, la última cotización
(producto, precio, peso y total, tomados de la llamada al motor) y los últimos
mensajes del cliente.
"""

import json
import re
from typing import Dict, List, Optional

from borrador import vigente
from database import obtener_borrador, obtener_chat, obtener_mensajes_chat, obtener_metricas_chat
from pricing_engine import GlobexPricingEngine

_TOPE = f"USD {GlobexPricingEngine.LIMITE_COTIZACION_AUTOMATICA:,.0f}"

MOTIVOS = {
    "asesor": "Pidió hablar con un asesor",
    "tope": f"Compra de más de {_TOPE} (cotización personalizada)",
    "seguimiento": "Consulta de seguimiento de paquete",
    "viajero": "Consulta por modalidad viajero",
    "restringido": "Mercancía restringida: revisar requisitos antes de cotizar",
    "consulta": "Consulta que requiere revisión del asesor",
    "sin_derivar": "Sin derivación (vista previa del resumen para el asesor)",
}
ULTIMOS_MENSAJES = 6  # todos los de un chat típico; antes 3 y se perdían hechos del inicio


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


# Datos que el cliente dijo que aún no tiene (guía §7: pendientes reales para el asesor)
_TIENDA_PENDIENTE = re.compile(
    r"(?:no|a[uú]n no|todav[ií]a no)\s+(?:he\s+)?(?:elegid[oa]|eleg[ií]|decid[ií]do|decid[ií]|decido|elijo|s[eé]\s+(?:en\s+)?(?:qu[eé]|cu[aá]l))\b[^.;]{0,25}\btienda"
    r"|\btienda\s+(?:por|a|sin)\s+(?:definir|elegir|decidir)|\bsin\s+tienda\b", re.IGNORECASE)
_CANTIDAD_PENDIENTE = re.compile(
    r"no\s+s[eé]\s+cu[aá]nt[oa]s\b(?!\s+(?:kilos?|kg|gramos?|d[oó]lares|usd|pesa|cuesta))|cantidad\s+(?:pendiente|por\s+definir|a\s+definir|sin\s+definir)"
    r"|(?:deja|dejar|dejo)\s+(?:la\s+)?cantidad|sin\s+definir\s+(?:la\s+)?cantidad", re.IGNORECASE)


def _pendiente_dicho(patron, mensajes: List[str]) -> bool:
    return any(patron.search(m or "") for m in mensajes)


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
    elif cotizacion and cotizacion.get("pendientes_datos"):
        pendientes.append("Pedir " + ", ".join(cotizacion["pendientes_datos"]))
    elif cotizacion and cotizacion.get("aceptada", True):
        pendientes.append("Validar la cotización y enviar el PDF formal")
    elif cotizacion and not cotizacion.get("intento", True):
        pendientes.append("Preparar la cotización con estos datos")
    elif cotizacion:
        pendientes.append("Revisar los datos del pedido: Globix no pudo cotizarlo")
    else:
        pendientes.append("Entender la consulta y responder")
    if motivo == "asesor":
        pendientes.insert(0, "Continuar la atención que pidió el cliente")
    items = (cotizacion or {}).get("items", [])
    extra = []
    if items and _pendiente_dicho(_CANTIDAD_PENDIENTE, mensajes):
        extra.append("Confirmar la cantidad (el cliente aún no la definió)")
    if items and not any(i.get("tienda") for i in items) and _pendiente_dicho(_TIENDA_PENDIENTE, mensajes):
        extra.append("Confirmar la tienda de EE. UU. (el cliente aún no la eligió)")
    pendientes[1:1] = extra  # antes de las tareas generales, para que no se pierdan en el máximo
    sin_tax = [i["producto"] or "el producto" for i in (cotizacion or {}).get("items", [])
               if i.get("tax_estado") == "desconocido" and i.get("precio") is not None]
    if sin_tax:
        pendientes.append(f"Confirmar el TAX de {', '.join(sin_tax)} (no lo dio; se estimó el 7 %)")
    incluido = [i["producto"] or "el producto" for i in (cotizacion or {}).get("items", [])
                if i.get("tax_estado") == "incluido_sin_desglose"]
    if incluido:
        pendientes.append(f"El precio de {', '.join(incluido)} ya incluye el TAX (sin desglose): no sumar otro 7 %")
    if not chat.get("nombre_cliente"):
        pendientes.append("Nombre del cliente (Globix ya se lo pidió)")
    return pendientes[:5]


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


def _productos_del_borrador(borrador: Optional[Dict]) -> List[Dict]:
    """Líneas del borrador del pedido en el formato del resumen."""
    return [{"producto": (l.get("producto") or "").strip(), "tienda": (l.get("tienda") or "").strip(),
             "precio": l.get("precio_unitario_usd"), "cantidad": int(l.get("cantidad") or 1),
             "peso": l.get("peso_kg"), "tax_estado": (l.get("tax") or {}).get("estado"),
             "tax_monto": (l.get("tax") or {}).get("monto_usd"), "origen_peso": l.get("origen_peso"),
             "origen_precio": l.get("origen_precio")}
            for l in (borrador or {}).get("lineas", [])]


def _sin_ids(lineas: List[Dict]) -> List[Dict]:
    return [{k: v for k, v in l.items() if k != "id"} for l in lineas]


def construir_resumen(chat_id: str, motivo: Optional[str], detalle: str = "") -> str:
    """Texto del resumen (formato WhatsApp: *negrita*), tal como lo ve el asesor en la consola.

    Los datos del pedido salen del borrador estructurado del chat (existe aunque no se haya
    cotizado); si no hay borrador, de la última llamada al motor.
    """
    chat = obtener_chat(chat_id) or {}
    nombre = chat.get("nombre_cliente") or "Aún no dio su nombre"
    borrador = obtener_borrador(chat_id)
    if borrador and not vigente(borrador):  # de una conversación anterior (más de 12 h)
        borrador = None
    cotizacion = None if borrador else _ultima_cotizacion(chat_id)
    mensajes = _ultimos_mensajes_cliente(chat_id)
    items = _productos_del_borrador(borrador) if borrador else _productos_de(cotizacion)
    if borrador:  # para el peso total y los pendientes, el borrador hace de "cotización"
        cotizacion = {"peso_total_kg": borrador.get("peso_total_kg"),
                      "pendientes_datos": borrador.get("pendientes", []), "items": items,
                      "aceptada": bool((borrador.get("ultima_cotizacion") or {}).get("aceptada")),
                      "intento": bool(borrador.get("ultima_cotizacion"))} if items else None
    producto = ", ".join(i["producto"] for i in items if i["producto"])
    servicio = chat.get("servicio") or "—"
    lineas = [
        f"*Motivo:* {MOTIVOS.get(motivo, motivo or 'Derivación')}" + (f" ({detalle})" if detalle else ""),
        f"*Necesidad:* {_necesidad(motivo, producto, servicio, detalle)}",
        f"*Cliente:* {nombre} · ID {chat_id}",
        f"*Servicio:* {servicio}",
    ]

    cantidad_pendiente = _pendiente_dicho(_CANTIDAD_PENDIENTE, mensajes)
    con_embalaje = len(items) == 1 and any("con embalaje" in (m or "").lower() for m in mensajes)
    if items or chat.get("cotizacion_total"):
        partes = []
        for item in items:  # productos, cantidades y tiendas del pedido
            texto = item["producto"] or "Producto"
            if item["tienda"]:
                texto += f" ({item['tienda']})"
            if item["precio"] is not None:
                derivado = (item.get("origen_precio") == "derivado" and item.get("tax_estado") == "confirmado"
                            and item.get("tax_monto") is not None)
                if derivado:  # el cliente dio el precio final con el TAX incluido: se muestra ese precio
                    final = item["precio"] + item["tax_monto"] / max(item["cantidad"], 1)
                    unidades = "cantidad por definir ×" if cantidad_pendiente else f"{item['cantidad']} ×"
                    texto += f" {unidades} USD {final:,.2f} (precio final, incluye TAX USD {item['tax_monto']:,.2f})"
                elif cantidad_pendiente:  # no se asume una unidad que el cliente no confirmó (CHAT020)
                    texto += f" cantidad por definir × USD {item['precio']:,.2f} c/u"
                else:
                    texto += f" {item['cantidad']} × USD {item['precio']:,.2f}"
            if item["peso"] is not None:
                texto += f", {item['peso']:g} kg" + (" con embalaje" if con_embalaje else "")
                if item.get("origen_peso") == "catalogo":
                    texto += " (estimado de catálogo)"
            # Estado del TAX: declarado por el cliente o estimado (guía §7.2)
            if item.get("tax_estado") == "incluido_sin_desglose":
                texto += " (TAX incluido)"
            elif item.get("tax_estado") == "incluido_desglosado" and item.get("tax_monto") is not None:
                texto += f" (incluye TAX USD {item['tax_monto']:,.2f})"
            elif item.get("tax_estado") == "cero_confirmado":
                texto += " (TAX 0 confirmado)"
            elif (item.get("tax_estado") == "confirmado" and item.get("tax_monto") is not None
                  and item.get("origen_precio") != "derivado"):
                texto += f" (TAX USD {item['tax_monto']:,.2f})"
            partes.append(texto)
        if cotizacion and cotizacion.get("peso_total_kg") is not None:
            partes.append(f"peso total {float(cotizacion['peso_total_kg']):g} kg")
        intento = (borrador or {}).get("ultima_cotizacion") or {}
        # Una corrección posterior aún no cotizada no se mezcla con la cotización emitida (guía §7.1)
        cambio = bool(intento.get("lineas")) and _sin_ids(intento["lineas"]) != _sin_ids(borrador.get("lineas", []))
        if chat.get("cotizacion_total") and not cambio:
            partes.append(f"total USD {chat['cotizacion_total']:,.2f}"
                          + (" (referencial por 1 unidad)" if cantidad_pendiente else ""))
        if cambio:
            rotulo = "*Pedido vigente (sin recotizar):*"
        else:
            rotulo = "*Cotización:*" if (cotizacion or {}).get("aceptada", True) else "*Pedido (sin cotizar):*"
        lineas.append(f"{rotulo} {', '.join(partes)}")
        if cambio and intento.get("total_usd"):
            lineas.append(f"*Cotización previa:* total USD {intento['total_usd']:,.2f} (antes de la corrección)")

    lineas.append("*Pendientes:* " + "; ".join(_pendientes(motivo, detalle, chat, cotizacion, mensajes)))
    if mensajes:
        lineas.append("*Mensajes del cliente:*")
        lineas += [f"• {m[:400]}" for m in mensajes]
    return "\n".join(lineas)
