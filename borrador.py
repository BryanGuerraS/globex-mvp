"""Borrador estructurado del pedido de cada chat (guía de criterios, §5 y §8.20–8.25).

Guarda lo que Globix ya entendió del pedido aunque todavía no haya cotización: una línea por
producto con su id estable (P1, P2...), tienda, cantidad, precio (base o final), estado del TAX,
peso con su origen y lo que falta. Lo actualizan `registrar_datos_pedido` (datos parciales) y
`calcular_cotizacion` (pedido completo o intento rechazado). Lo leen el resumen del caso y la API
de evaluación, así WhatsApp y la API usan la misma fuente.

Solo guarda datos ya validados contra el texto del cliente (validaciones.py): nada inventado.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import ahora, guardar_borrador, obtener_borrador
from validaciones import precio_derivado, tax_cero_dicho, tax_incluido_dicho

# Estados del TAX de tienda (guía §2.6)
TAX_CONFIRMADO = "confirmado"            # el cliente dijo el monto
TAX_CERO = "cero_confirmado"             # el cliente dijo que el TAX es 0
TAX_INCLUIDO = "incluido_sin_desglose"   # el precio ya lo incluye o la tienda no lo cobra
TAX_INCLUIDO_DESGLOSADO = "incluido_desglosado"  # el precio final incluye un TAX cuyo monto dijo el cliente
TAX_DESCONOCIDO = "desconocido"          # se estima el 7 % de referencia


def estado_tax(bruto: Dict, tax_validado: Optional[float]) -> str:
    """Estado del TAX de una línea a partir de lo que pasó el LLM y lo que aceptó la validación."""
    if tax_validado is None:
        return TAX_DESCONOCIDO
    if bruto.get("sin_tax") is True:
        tax_bruto = bruto.get("tax_tienda_usd")
        return TAX_INCLUIDO_DESGLOSADO if tax_bruto not in (None, "") and float(tax_bruto) > 0 else TAX_INCLUIDO
    if tax_validado == 0:
        tax_bruto = bruto.get("tax_tienda_usd")
        return TAX_CERO if tax_bruto is not None and float(tax_bruto) == 0 else TAX_INCLUIDO
    return TAX_CONFIRMADO


def _linea(i: int, item: Dict, bruto: Dict, pesos_catalogo=(), peso_total: Optional[float] = None,
           textos=()) -> Dict:
    tax = item.get("tax")
    estado = estado_tax(bruto, tax) if item.get("precio_unitario") is not None else TAX_DESCONOCIDO
    # "TAX confirmado de USD 0" aunque el LLM lo marque como incluido: es un cero confirmado (VCHAT001)
    if estado == TAX_INCLUIDO and tax == 0 and tax_cero_dicho(list(textos)):
        estado = TAX_CERO
    # "ese total ya incluye USD 2,94 de TAX" aunque el LLM no pase el monto (VCHAT007)
    monto_incluido = tax_incluido_dicho(list(textos)) if estado == TAX_INCLUIDO else None
    if monto_incluido:
        estado = TAX_INCLUIDO_DESGLOSADO
        bruto = {**bruto, "tax_tienda_usd": monto_incluido}
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
        "tipo_precio": "final" if estado in (TAX_INCLUIDO, TAX_INCLUIDO_DESGLOSADO) else "base",
        # "derivado": base = total que dijo el cliente − su TAX (guía §5.3); "cliente": lo dijo tal cual
        "origen_precio": (None if item.get("precio_unitario") is None else
                          "derivado" if precio_derivado(item.get("precio_unitario"), tax, item.get("cantidad") or 1,
                                                        list(textos)) else "cliente"),
        "tax": {"estado": estado,
                "monto_usd": (tax if estado == TAX_CONFIRMADO else
                              float(bruto["tax_tienda_usd"]) if estado == TAX_INCLUIDO_DESGLOSADO else
                              (0.0 if tax == 0 else None))},
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
              pesos_catalogo=(), textos=()) -> Dict:
    """Borrador a partir de las líneas validadas (mismo orden que `brutos`, lo que pasó el LLM)."""
    lineas = [_linea(i, item, brutos[i - 1] if i - 1 < len(brutos) and isinstance(brutos[i - 1], dict) else {},
                     pesos_catalogo, peso_total, textos)
              for i, item in enumerate(items, 1)]
    return {"lineas": lineas, "peso_total_kg": peso_total, "pendientes": pendientes_de(lineas, peso_total)}


def _clave(producto: Optional[str]) -> str:
    return " ".join((producto or "").lower().split())


def _ids_estables(lineas: List[Dict], anteriores: List[Dict]) -> None:
    """Un producto conserva su id (P1, P2...) aunque se agreguen, quiten o corrijan otros (guía §5.1)."""
    previos = {_clave(l.get("producto")): l["id"] for l in anteriores if l.get("producto")}
    usados = set()
    siguiente = max([int(l["id"][1:]) for l in anteriores if str(l.get("id", "")).startswith("P")] or [0]) + 1
    for linea in lineas:
        previo = previos.get(_clave(linea.get("producto")))
        if previo and previo not in usados:
            linea["id"] = previo
        else:
            linea["id"] = f"P{siguiente}"
            siguiente += 1
        usados.add(linea["id"])


def guardar(chat_id: str, borrador: Dict, cotizacion: Optional[Dict] = None) -> Dict:
    """Guarda el borrador. `cotizacion`: {"aceptada", "error", "total_usd"} del último intento."""
    anterior = obtener_borrador(chat_id) or {}
    if borrador.get("lineas") is not anterior.get("lineas") and anterior.get("lineas"):
        _ids_estables(borrador["lineas"], anterior["lineas"])
        borrador = {**borrador, "pendientes": pendientes_de(borrador["lineas"], borrador.get("peso_total_kg"))}
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


_PESO_EN_TEXTO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kg|kilos?|kilogramos?)(?![a-z])", re.IGNORECASE)


def completar_con_mensaje(chat_id: str, texto: str):
    """Si el último mensaje trae el único peso que faltaba ("Pesa 0,53 kg. Quiero un asesor"), lo
    registra: el LLM a veces deriva sin guardarlo y el resumen pedía un dato ya dado (VCHAT007)."""
    datos = obtener_borrador(chat_id)
    if not datos or not vigente(datos) or datos.get("peso_total_kg") is not None:
        return
    sin_peso = [l for l in datos.get("lineas", []) if l.get("peso_kg") is None]
    pesos = _PESO_EN_TEXTO.findall(texto or "")
    if len(sin_peso) == 1 and len(pesos) == 1:
        sin_peso[0]["peso_kg"] = float(pesos[0].replace(",", "."))
        sin_peso[0]["origen_peso"] = "cliente"
        guardar(chat_id, {**datos, "pendientes": pendientes_de(datos["lineas"], None)})


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
            "tax_tienda_usd": (linea["tax"]["monto_usd"]
                               if estado in (TAX_CONFIRMADO, TAX_CERO, TAX_INCLUIDO_DESGLOSADO) else None),
            "sin_tax": True if estado in (TAX_INCLUIDO, TAX_INCLUIDO_DESGLOSADO) else None,
            "tax_estado": estado, "tipo_precio": linea["tipo_precio"], "origen_peso": linea["origen_peso"],
            "origen_precio": linea.get("origen_precio"),
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


_TEXTO_TAX = {TAX_CONFIRMADO: "TAX dicho por el cliente", TAX_CERO: "TAX 0 confirmado",
              TAX_INCLUIDO_DESGLOSADO: "precio final con el TAX dicho por el cliente incluido",
              TAX_INCLUIDO: "precio con TAX incluido", TAX_DESCONOCIDO: "TAX no dicho (7 % de referencia)"}


def describir_lineas(borrador: Optional[Dict]) -> List[str]:
    """Una línea legible por producto del borrador (para el LLM y el resumen)."""
    salida = []
    for l in (borrador or {}).get("lineas", []):
        partes = [l.get("producto") or "producto sin nombre"]
        if l.get("tienda"):
            partes[0] += f" ({l['tienda']})"
        if l.get("precio_unitario_usd") is not None:
            precio = f"USD {l['precio_unitario_usd']:,.2f}"
            partes.append(f"{l['cantidad']} × {precio}" if (l.get("cantidad") or 1) > 1 else precio)
        else:
            partes.append("precio pendiente")
        if l.get("peso_kg") is not None:
            partes.append(f"{l['peso_kg']:g} kg" + (" (catálogo)" if l.get("origen_peso") == "catalogo" else ""))
        elif l.get("origen_peso") != "peso_total":
            partes.append("peso pendiente")
        tax = l.get("tax") or {}
        texto_tax = _TEXTO_TAX.get(tax.get("estado"), "")
        if tax.get("estado") == TAX_CONFIRMADO and tax.get("monto_usd") is not None:
            texto_tax = f"TAX USD {tax['monto_usd']:,.2f} dicho por el cliente"
        partes.append(texto_tax)
        salida.append(f"{l['id']}: " + ", ".join(p for p in partes if p))
    if (borrador or {}).get("peso_total_kg") is not None:
        salida.append(f"Peso total del pedido: {borrador['peso_total_kg']:g} kg")
    return salida


HORAS_VIGENCIA = 12  # mismo horizonte que el historial de la conversación


def vigente(borrador: Optional[Dict]) -> bool:
    """El borrador es de esta conversación (actualizado en las últimas 12 h)."""
    try:
        cuando = datetime.strptime((borrador or {}).get("actualizado_at", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return ahora().replace(tzinfo=None) - cuando <= timedelta(hours=HORAS_VIGENCIA)


def bloque_para_llm(borrador: Optional[Dict]) -> str:
    """Pedido vigente para el system prompt: así el LLM agrega, quita o corrige sin perder datos."""
    lineas = describir_lineas(borrador) if vigente(borrador) else []
    if not lineas:
        return ""
    return ("\n\nPEDIDO VIGENTE (datos que el cliente ya dio en esta conversación):\n- " + "\n- ".join(lineas) +
            "\nPara agregar, quitar o corregir un producto, vuelve a pasar la lista COMPLETA con ese cambio y los "
            "demás datos tal cual (corregir no es agregar otra línea; agregar no reemplaza a los demás). "
            "Si el cliente pasa a otro tema o a un producto nuevo sin relación, no arrastres este pedido.")
