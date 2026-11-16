"""Borrador estructurado del pedido de cada chat (guía de criterios, §5 y §8.20–8.25).

Guarda lo que Globix ya entendió del pedido aunque todavía no haya cotización: una línea por
producto con su id estable (P1, P2...), tienda, cantidad, precio (base o final), estado del TAX,
peso con su origen y lo que falta. Lo actualizan `registrar_datos_pedido` (datos parciales) y
`calcular_cotizacion` (pedido completo o intento rechazado). Lo leen el resumen del caso y la API
de evaluación, así WhatsApp y la API usan la misma fuente.

Solo guarda datos ya validados contra el texto del cliente (validaciones.py): nada inventado.
"""

from typing import Dict, List, Optional

from database import ahora, guardar_borrador, obtener_borrador

# Estados del TAX de tienda (guía §2.6)
TAX_CONFIRMADO = "confirmado"            # el cliente dijo el monto
TAX_CERO = "cero_confirmado"             # el cliente dijo que el TAX es 0
TAX_INCLUIDO = "incluido_sin_desglose"   # el precio ya lo incluye o la tienda no lo cobra
TAX_DESCONOCIDO = "desconocido"          # se estima el 7 % de referencia


def estado_tax(bruto: Dict, tax_validado: Optional[float]) -> str:
    """Estado del TAX de una línea a partir de lo que pasó el LLM y lo que aceptó la validación."""
    if tax_validado is None:
        return TAX_DESCONOCIDO
    if bruto.get("sin_tax") is True:
        return TAX_INCLUIDO
    if tax_validado == 0:
        tax_bruto = bruto.get("tax_tienda_usd")
        return TAX_CERO if tax_bruto is not None and float(tax_bruto) == 0 else TAX_INCLUIDO
    return TAX_CONFIRMADO


def _linea(i: int, item: Dict, bruto: Dict, pesos_catalogo=(), peso_total: Optional[float] = None) -> Dict:
    tax = item.get("tax")
    estado = estado_tax(bruto, tax) if item.get("precio_unitario") is not None else TAX_DESCONOCIDO
    peso = item.get("peso_kg")
    if peso is not None:
        origen = "catalogo" if any(abs(peso - p) < 1e-9 for p in pesos_catalogo) else "cliente"
    else:
        origen = "peso_total" if peso_total is not None else None
    return {
        "id": f"P{i}",
        "producto": item.get("producto"),
        "tienda": item.get("tienda"),
        "cantidad": item.get("cantidad") or 1,
        "precio_unitario_usd": item.get("precio_unitario"),
        # base = precio sin TAX (se suma el TAX); final = el cliente dijo que ya lo incluye
        "tipo_precio": "final" if estado == TAX_INCLUIDO else "base",
        "tax": {"estado": estado, "monto_usd": tax if estado == TAX_CONFIRMADO else (0.0 if tax == 0 else None)},
        "peso_kg": peso,
        "origen_peso": origen,
    }


def pendientes_de(lineas: List[Dict], peso_total: Optional[float]) -> List[str]:
    """Datos que faltan para cotizar, por línea."""
    faltan = []
    for linea in lineas:
        nombre = linea["producto"] or linea["id"]
        if not linea["producto"]:
            faltan.append(f"{linea['id']}: nombre del producto")
        if linea["precio_unitario_usd"] is None:
            faltan.append(f"{nombre}: precio en USD")
        if linea["peso_kg"] is None and peso_total is None:
            faltan.append(f"{nombre}: peso en kg")
    return faltan


def construir(items: List[Dict], brutos: List[Dict], peso_total: Optional[float],
              pesos_catalogo=()) -> Dict:
    """Borrador a partir de las líneas validadas (mismo orden que `brutos`, lo que pasó el LLM)."""
    lineas = [_linea(i, item, brutos[i - 1] if i - 1 < len(brutos) and isinstance(brutos[i - 1], dict) else {},
                     pesos_catalogo, peso_total)
              for i, item in enumerate(items, 1)]
    return {"lineas": lineas, "peso_total_kg": peso_total, "pendientes": pendientes_de(lineas, peso_total)}


def guardar(chat_id: str, borrador: Dict, cotizacion: Optional[Dict] = None) -> Dict:
    """Guarda el borrador. `cotizacion`: {"aceptada", "error", "total_usd"} del último intento."""
    anterior = obtener_borrador(chat_id) or {}
    datos = {**borrador, "actualizado_at": ahora().strftime("%Y-%m-%d %H:%M:%S"),
             "ultima_cotizacion": cotizacion if cotizacion is not None else anterior.get("ultima_cotizacion"),
             # Condiciones de admisión conocidas (p. ej. el cliente dijo que el producto es usado)
             "condiciones": borrador.get("condiciones") or anterior.get("condiciones") or {}}
    guardar_borrador(chat_id, datos)
    return datos


def registrar_intento(chat_id: str, cotizacion: Dict):
    """Anota el resultado de un intento de cotización sin cambiar las líneas."""
    anterior = obtener_borrador(chat_id)
    if anterior is None:
        anterior = {"lineas": [], "peso_total_kg": None, "pendientes": []}
    guardar(chat_id, anterior, cotizacion)


def leer(chat_id: str) -> Optional[Dict]:
    return obtener_borrador(chat_id)


def productos_para_api(borrador: Optional[Dict]) -> List[Dict]:
    """Líneas en el formato de `datos_recopilados` (campos de siempre + estado del TAX y origen)."""
    salida = []
    for linea in (borrador or {}).get("lineas", []):
        estado = linea["tax"]["estado"]
        salida.append({
            "id": linea["id"], "producto": linea["producto"] or "", "tienda": linea["tienda"] or "",
            "precio": linea["precio_unitario_usd"], "cantidad": linea["cantidad"], "peso": linea["peso_kg"],
            "tax_tienda_usd": linea["tax"]["monto_usd"] if estado in (TAX_CONFIRMADO, TAX_CERO) else None,
            "sin_tax": True if estado == TAX_INCLUIDO else None,
            "tax_estado": estado, "tipo_precio": linea["tipo_precio"], "origen_peso": linea["origen_peso"],
        })
    return salida


def marcar_usado(chat_id: str, texto_cliente: str):
    """El cliente dijo que su ropa, juguete o repuesto es usado: no se cotiza mientras no diga que es nuevo."""
    anterior = obtener_borrador(chat_id) or {"lineas": [], "peso_total_kg": None, "pendientes": []}
    condiciones = {**anterior.get("condiciones", {}), "usado": {"texto": texto_cliente}}
    guardar(chat_id, {**anterior, "condiciones": condiciones})


def texto_usado(chat_id: str) -> str:
    """Mensaje del cliente en que dijo que el producto es usado ("" si no lo dijo)."""
    return ((obtener_borrador(chat_id) or {}).get("condiciones", {}).get("usado") or {}).get("texto", "")
