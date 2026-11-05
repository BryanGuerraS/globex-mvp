"""Validaciones en código de lo que interpreta el LLM.

El LLM solo extrae datos; antes de llegar al motor de cotización se comprueba que:
- valor y peso sean números finitos y mayores a cero;
- el valor aparezca en lo que escribió el cliente (en dígitos o en palabras,
  como "mil dólares");
- el peso aparezca en lo que escribió el cliente (en kg, g, lb u oz) o venga
  del catálogo de pesos referenciales.
"""

import math
import re
import unicodedata
from typing import Iterable, List, Optional, Tuple, Union

# Tolerancia relativa para aceptar conversiones de unidades y redondeos del LLM.
_TOLERANCIA = 0.02

# Factores de conversión a kg de unidades que el cliente puede usar.
_FACTORES_A_KG = (1.0, 0.001, 0.45359237, 0.028349523)  # kg, g, lb, oz

_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _interpretar_numero(token: str) -> List[float]:
    """Devuelve las lecturas posibles de un número escrito por el cliente.

    "1,200" y "1.200" pueden ser mil doscientos (separador de miles) o 1.2
    (decimal); se devuelven ambas lecturas y la comparación decide.
    """
    lecturas = set()
    if "," not in token and "." not in token:
        lecturas.add(float(token))
        return list(lecturas)

    # Lectura como separador de miles: grupos de exactamente 3 dígitos.
    partes = re.split(r"[.,]", token)
    if all(len(p) == 3 for p in partes[1:]):
        lecturas.add(float("".join(partes)))

    # Lectura con el último separador como decimal.
    entero, decimal = re.split(r"[.,](?=\d+$)", token)
    entero = re.sub(r"[.,]", "", entero)
    lecturas.add(float(f"{entero}.{decimal}"))
    return list(lecturas)


_PALABRAS_NUMERO = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500,
    "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700, "ochocientos": 800,
    "ochocientas": 800, "novecientos": 900, "novecientas": 900,
    "medio": 0.5, "media": 0.5,
}
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+")


def _numeros_en_palabras(texto: str) -> List[float]:
    """Lee montos y pesos escritos en palabras o mixtos.

    "mil dólares" → 1000, "dos mil quinientos" → 2500, "2 mil" → 2000,
    "1.5 mil" → 1500, "medio kilo" → 0.5, "kilo y medio" → 1.5,
    "dos kilos y medio" → 2.5.
    """
    tokens = _TOKEN.findall(_sin_tildes(texto.lower()))
    numeros: List[float] = []
    total, actual, activo = 0.0, 0.0, False
    ultimo: Optional[float] = None  # último número cerrado, para "... y medio"

    def cerrar():
        nonlocal total, actual, activo, ultimo
        if activo:
            ultimo = total + actual
            numeros.append(ultimo)
        total, actual, activo = 0.0, 0.0, False

    for i, tok in enumerate(tokens):
        if tok[0].isdigit():
            cerrar()
            lecturas = _interpretar_numero(tok)
            if i + 1 < len(tokens) and tokens[i + 1] == "mil":
                numeros.extend(v * 1000 for v in lecturas)
            ultimo = lecturas[0]
        elif tok == "mil":
            if i > 0 and tokens[i - 1][0].isdigit():
                continue  # ya se contó como "2 mil"
            total += (actual or 1) * 1000
            actual, activo = 0.0, True
        elif tok in ("medio", "media") and not activo:
            numeros.append(0.5)
            # "1 kilo y medio", "un kilo y medio"
            if ultimo is not None and i >= 2 and tokens[i - 1] == "y":
                numeros.append(ultimo + 0.5)
        elif tok in _PALABRAS_NUMERO:
            actual += _PALABRAS_NUMERO[tok]
            activo = True
        elif tok == "y" and activo:
            continue  # "treinta y cinco", "dos y medio"
        else:
            cerrar()
    cerrar()
    return numeros


def numeros_en_texto(textos: Iterable[str]) -> List[float]:
    """Extrae todos los números (con sus lecturas posibles) de los textos dados.

    Reconoce dígitos ("1,200", "2.5"), el sufijo "k" ("1.5k") y números en
    palabras ("mil dólares", "medio kilo").
    """
    numeros: List[float] = []
    for texto in textos:
        if not texto:
            continue
        for m in _NUMERO.finditer(texto):
            lecturas = _interpretar_numero(m.group())
            numeros.extend(lecturas)
            siguiente = texto[m.end(): m.end() + 1].lower()
            if siguiente == "k":
                numeros.extend(v * 1000 for v in lecturas)
        numeros.extend(_numeros_en_palabras(texto))
    return numeros


def _cerca(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, abs(b) * _TOLERANCIA)


def _a_numero(valor) -> Optional[float]:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def validar_argumentos_cotizacion(
    args: dict,
    textos_cliente: Iterable[str],
    pesos_referenciales: Iterable[float] = (),
) -> Union[Tuple[float, float], str]:
    """Valida los argumentos que el LLM pasa a calcular_cotizacion.

    Devuelve (valor_usd, peso_kg) si son válidos, o un texto con el motivo del
    rechazo para devolvérselo al LLM como resultado de la herramienta.
    """
    valor = _a_numero(args.get("valor_producto_usd"))
    peso = _a_numero(args.get("peso_kg"))

    if valor is None or peso is None:
        return "Faltan el valor en USD o el peso en kg, o no son números. Pide al cliente el dato que falta."
    if valor <= 0 or peso <= 0:
        return "El valor y el peso deben ser mayores a cero. Pide al cliente que confirme los datos."

    numeros = numeros_en_texto(textos_cliente)

    if not any(_cerca(valor, n) for n in numeros):
        return (
            f"El valor {valor} USD no aparece en los mensajes del cliente. "
            "No lo supongas: pide al cliente que confirme el precio del producto en USD."
        )

    peso_del_cliente = any(
        _cerca(peso, n * factor) for n in numeros for factor in _FACTORES_A_KG
    )
    peso_de_catalogo = any(_cerca(peso, p) for p in pesos_referenciales)
    if not (peso_del_cliente or peso_de_catalogo):
        return (
            f"El peso {peso} kg no aparece en los mensajes del cliente ni en el catálogo. "
            "No lo supongas: usa consultar_peso_producto o pide al cliente el peso."
        )

    return valor, peso


# ---------------- Nombre que da el cliente ----------------

_PREFIJOS_NOMBRE = re.compile(
    r"^(hola[,!.\s]*)?(me llamo|mi nombre es|soy|es|claro[,\s]+soy|claro[,\s]+me llamo)\s+",
    re.IGNORECASE,
)
# Palabras que delatan que el mensaje no es un nombre.
_NO_NOMBRES = {
    "ok", "okay", "si", "no", "hola", "gracias", "listo", "ya", "bueno", "perfecto",
    "vale", "dale", "buenas", "buenos", "dias", "tardes", "noches", "quiero", "cotizar",
    "envio", "paquete", "precio", "cuanto", "cuando", "donde", "como", "que", "por",
    "para", "con", "un", "una", "el", "mi", "tu",
    "asesor", "ayuda", "favor", "espero", "esperando", "tracking", "dolares", "kg",
}
_PALABRA_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'-]{2,25}$")


def extraer_nombre(texto: str) -> Optional[str]:
    """Extrae el nombre de respuestas como "Ana", "me llamo Ana Pérez" o "Soy José".

    Devuelve None si el mensaje no parece un nombre (una pregunta, "ok", etc.).
    """
    if not texto:
        return None
    limpio = texto.strip().strip(".!¡¿?,;:").strip()
    limpio = _PREFIJOS_NOMBRE.sub("", limpio).strip().strip(".!¡¿?,;:")
    palabras = limpio.split()
    if not 1 <= len(palabras) <= 4:
        return None
    if not all(_PALABRA_NOMBRE.match(p) for p in palabras):
        return None
    if any(_sin_tildes(p.lower()) in _NO_NOMBRES for p in palabras):
        return None
    return " ".join(p[:1].upper() + p[1:].lower() for p in palabras)
