"""Baseline "modelo simple" del E5: Globix SIN LLM, con reglas de palabras clave.

Reemplaza solo la llamada al LLM por reglas deterministas (palabras clave y expresiones
regulares). Todo lo demás es el mismo sistema: guardrail de mercancía, motor de
cotización, FAQ aprobadas, derivación, textos y validaciones. Así la comparación con
Globix aísla lo que aporta la IA (evidencias 2.3 y 4.2 del P4).

Las reglas se escribieron a partir del prompt y las herramientas de Globix, sin mirar
el set reservado.

Uso (mismo flujo y mismos casos que la evaluación con LLM):
    python evaluacion/evaluar.py --casos evaluacion/reservado/casos_reservados.json --repeticiones 1 --reglas
"""

import json
import re
import unicodedata
import uuid
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

TEXTO_PIDE_DATOS = ("¡Claro! 😊 Cuéntame qué producto quieres traer, su precio en USD y cuánto pesa en kg. "
                    "Por ejemplo: _Laptop Lenovo, USD 650, 2.5 kg_.")
TEXTO_PIDE_PESO = "¿Cuánto pesa aproximadamente en kg? 📦"

_DERIVAR = re.compile(r"\b(asesor\w*|humano|persona|ejecutiv\w+|operador\w*|ll[a]m(en|ame|eme|ada|ar)\w*|hablar con alguien)\b")
_SEGUIMIENTO = re.compile(r"\b(tracking|rastre\w*|mi paquete|mi pedido|mi envio|donde esta|ya llego|estado de mi|guia)\b")
_VIAJERO = re.compile(r"\b(viajero|maleta|equipaje)\b")
_COTIZAR = re.compile(r"\b(cotiz\w*|cuanto (cuesta|sale|cobran|seria|me sale)|precio|tarifa|costo)\b")
_FAQ = [
    ("direccion_miami", re.compile(r"\b(direccion|almacen|warehouse|casillero|miami)\b")),
    ("provincias", re.compile(r"\b(provincia\w*|arequipa|trujillo|cusco|piura|chiclayo|agencia|olva|shalom)\b")),
    ("plazos_entrega", re.compile(r"\b(cuanto (tiempo|demora|tarda)|demora\w*|plazo\w*|tarda\w*|dias)\b")),
    ("pagos", re.compile(r"\b(pag(o|ar|os)|yape|plin|transferencia|tarjeta|soles)\b")),
    ("como_funciona", re.compile(r"\b(como funciona|como (es|hago|trabajan)|proceso|pasos|informacion|info)\b")),
]
_NUM = r"(\d+(?:[.,]\d+)?)"
_VALOR = re.compile(rf"(?:usd|us\$|\$)\s*{_NUM}|{_NUM}\s*(?:usd|dolares|dolar|\$)")
_PESO = re.compile(rf"{_NUM}\s*(kg|kilos?|kilogramos?|gr|g|gramos?|lb|lbs|libras?)\b")
_A_KG = {"kg": 1.0, "kilo": 1.0, "kilos": 1.0, "kilogramo": 1.0, "kilogramos": 1.0, "g": 0.001,
         "gr": 0.001, "gramo": 0.001, "gramos": 0.001, "lb": 0.45359237, "lbs": 0.45359237,
         "libra": 0.45359237, "libras": 0.45359237}


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def _numero(s: str) -> float:
    return float(s.replace(",", "."))


def extraer_valor_y_peso(texto: str) -> Tuple[Optional[float], Optional[float]]:
    t = _normalizar(texto)
    peso = None
    m = _PESO.search(t)
    if m:
        peso = round(_numero(m.group(1)) * _A_KG[m.group(2)], 3)
    sin_peso = _PESO.sub(" ", t)
    v = _VALOR.search(sin_peso)
    valor = _numero(v.group(1) or v.group(2)) if v else None
    return valor, peso


def decidir(textos_usuario: List[str]) -> Tuple[str, Dict]:
    """Devuelve (herramienta o 'texto', argumentos o {'contenido': ...}) para el último mensaje."""
    actual = _normalizar(textos_usuario[-1] if textos_usuario else "")
    if _DERIVAR.search(actual):
        return "derivar_a_asesor", {"motivo": None}
    if _SEGUIMIENTO.search(actual):
        return "clasificar_como_seguimiento", {"codigo_tracking": None}
    if _VIAJERO.search(actual):
        return "clasificar_como_viajero", {"detalle": None}
    # Datos de cotización: del mensaje actual, completados con los anteriores
    valor, peso = extraer_valor_y_peso(textos_usuario[-1] if textos_usuario else "")
    for anterior in reversed(textos_usuario[:-1]):
        v, p = extraer_valor_y_peso(anterior)
        valor, peso = valor if valor is not None else v, peso if peso is not None else p
    if valor is not None and peso is not None:
        return "calcular_cotizacion", {"valor_producto_usd": valor, "peso_kg": peso, "producto": None}
    if valor is not None:
        return "consultar_peso_producto", {"nombre_producto": textos_usuario[-1]}
    for tema, patron in _FAQ:
        if patron.search(actual):
            return "consultar_faq_comercial", {"tema": tema}
    if _COTIZAR.search(actual):
        return "texto", {"contenido": TEXTO_PIDE_DATOS}
    return "mostrar_menu", {}


def _respuesta(contenido: Optional[str] = None, herramienta: Optional[str] = None, args: Optional[Dict] = None):
    llamadas = None
    if herramienta:
        llamadas = [SimpleNamespace(id=f"r{uuid.uuid4().hex[:8]}", type="function",
                                    function=SimpleNamespace(name=herramienta, arguments=json.dumps(args or {})))]
    mensaje = SimpleNamespace(content=contenido, tool_calls=llamadas, role="assistant")
    return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)],
                           usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0))


class ClienteReglas:
    """Imita la interfaz client.chat.completions.create de OpenAI/Groq con reglas."""

    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, messages: List[Dict], **_):
        ultimo = messages[-1]
        textos = [m["content"] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if ultimo.get("role") == "tool":
            # Vuelve el resultado del catálogo de pesos: cotizar si hay peso, si no pedirlo
            try:
                datos = json.loads(ultimo.get("content") or "{}")
            except json.JSONDecodeError:
                datos = {}
            valor, _ = extraer_valor_y_peso(" ".join(textos[-3:]))
            if datos.get("peso_kg") and valor is not None and not datos.get("error"):
                return _respuesta(herramienta="calcular_cotizacion",
                                  args={"valor_producto_usd": valor, "peso_kg": float(datos["peso_kg"]),
                                        "producto": datos.get("producto")})
            return _respuesta(contenido=TEXTO_PIDE_PESO)
        herramienta, args = decidir(textos[-3:])
        if herramienta == "texto":
            return _respuesta(contenido=args["contenido"])
        return _respuesta(herramienta=herramienta, args=args)
