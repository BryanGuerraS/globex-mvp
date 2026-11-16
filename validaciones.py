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
            # "pesa kilo y medio": "kilo" en singular ya es uno
            if i >= 2 and tokens[i - 1] == "y" and tokens[i - 2] in ("kilo", "kilogramo"):
                numeros.append(1.5)
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
    cantidad: int = 1,
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

    # El peso es el total; también vale el peso por unidad × cantidad ("cada uno pesa 0.3 kg")
    peso_del_cliente = any(
        _cerca(peso, n * factor * veces)
        for n in numeros for factor in _FACTORES_A_KG for veces in {1, cantidad}
    )
    peso_de_catalogo = any(_cerca(peso, p) for p in pesos_referenciales)
    if not (peso_del_cliente or peso_de_catalogo):
        return (
            f"El peso {peso} kg no aparece en los mensajes del cliente ni en el catálogo. "
            "No lo supongas: usa consultar_peso_producto o pide al cliente el peso."
        )

    return valor, peso


# ---------------- Cantidad de unidades ----------------

CANTIDAD_MAXIMA = 100


def validar_cantidad(args: dict, textos_cliente: Iterable[str]) -> Union[int, str]:
    """Unidades del producto (1 si el LLM no la pasa) o el motivo del rechazo.

    La cantidad tiene que estar en el texto del cliente (en dígitos o en palabras).
    """
    bruto = args.get("cantidad")
    if bruto is None:
        return 1
    cantidad = _a_numero(bruto)
    if cantidad is None or cantidad != int(cantidad) or not 1 <= cantidad <= CANTIDAD_MAXIMA:
        return f"La cantidad debe ser un número entero entre 1 y {CANTIDAD_MAXIMA}."
    cantidad = int(cantidad)
    if cantidad > 1 and not any(_cerca(cantidad, n) for n in numeros_en_texto(textos_cliente)):
        return (
            f"La cantidad {cantidad} no aparece en los mensajes del cliente. "
            "No la supongas: deja cantidad vacía si el cliente dio el precio total."
        )
    return cantidad


# ---------------- TAX de la tienda ----------------

_MENCIONA_TAX = re.compile(r"\b(tax|taxes|impuestos?|sales)\b")
# El precio ya trae el TAX, o la tienda no lo cobra. Desde el 14/11 (decisión del usuario) comprar en
# Amazon o eBay ya no basta, y "sin tax" significa que el precio NO lo incluye: se suma el 7 %.
_SIN_TAX = re.compile(
    r"\binclu\w*\W+(?:\w+\W+){0,5}?(?:tax|taxes|impuestos?)\b"  # "ya incluye USD 3,00 de TAX"
    r"|\b(?:tax|taxes|impuestos?)\W+(?:\w+\W+){0,3}?inclu\w*"
    r"|\bcon\s+(?:el\s+|los\s+)?(?:tax|taxes|impuestos?)\b"
    r"|\bno\s+(?:me\s+)?(?:cobra|cobran|paga|pague|pago|hay|tiene)\s+(?:el\s+)?(?:tax|taxes|impuestos?)\b"
)


def validar_tax_tienda(args: dict, textos_cliente: Iterable[str]) -> Union[Optional[float], str]:
    """Decide el TAX de tienda que se pasa al motor.

    Devuelve el TAX en USD que dijo el cliente, 0.0 si el precio ya lo incluye o la tienda no
    lo cobra (en cualquier tienda), None para usar el 7 % de referencia, o un texto
    con el motivo del rechazo. Lo que diga el LLM tiene que estar en el texto del cliente.
    """
    textos = list(textos_cliente)
    texto = _sin_tildes(" ".join(textos).lower())
    tax = args.get("tax_tienda_usd")
    if tax is not None:
        tax = _a_numero(tax)
        if tax is None or tax < 0:
            return "El TAX de la tienda debe ser un número mayor o igual a cero, en USD."
        if tax == 0:
            # "el checkout confirma TAX de USD 0": el cliente dijo un TAX de cero
            if _MENCIONA_TAX.search(texto) and any(n == 0 for n in numeros_en_texto(textos)):
                return 0.0
            args = {**args, "sin_tax": True}
        elif not (_MENCIONA_TAX.search(texto) and any(_cerca(tax, n) for n in numeros_en_texto(textos))):
            return (
                f"El TAX {tax} USD no aparece en los mensajes del cliente. "
                "No lo supongas: deja tax_tienda_usd vacío y el motor usa el 7 % de referencia."
            )
        else:
            return tax
    if args.get("sin_tax") is True:
        if not _SIN_TAX.search(texto):
            return (
                "El cliente no dijo que su precio incluye el TAX ni que la tienda no se lo cobra. "
                "Deja sin_tax vacío y el motor usa el 7 % de referencia."
            )
        return 0.0
    return None


# ---------------- Nombre que da el cliente ----------------

# Respuestas como "Sí, llamo Rashan", "Claro, me llamo Ana", "Ok, soy José", "Mi nombre: Luis"
_PREFIJOS_NOMBRE = re.compile(
    r"^((hola|s[ií]|claro|ok|okay|bueno|listo|dale|perfecto|vale)[,!.:\s]+)*"
    r"(me llamo|llamo|mi nombre es|mi nombre|nombre|soy|es)?[,:\s]*",
    re.IGNORECASE,
)
# Palabras que delatan que el mensaje no es un nombre.
_NO_NOMBRES = {
    "ok", "okay", "si", "no", "hola", "gracias", "listo", "ya", "bueno", "perfecto",
    "vale", "dale", "buenas", "buenos", "dias", "tardes", "noches", "quiero", "cotizar",
    "envio", "paquete", "precio", "cuanto", "cuando", "donde", "como", "que", "por",
    "para", "con", "un", "una", "el", "mi", "tu",
    "asesor", "ayuda", "favor", "espero", "esperando", "tracking", "dolares", "kg",
    "claro", "exacto", "correcto", "entendido", "genial", "excelente", "super", "okey",
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
    particulas = {"de", "del", "la", "las", "los", "y"}
    return " ".join(
        p.lower() if i > 0 and p.lower() in particulas else p[:1].upper() + p[1:].lower()
        for i, p in enumerate(palabras)
    )


# ---------------- Limpieza de respuestas libres del LLM ----------------

# Líneas completas entre paréntesis o corchetes: "(Esperando respuesta del cliente)"
_LINEA_NOTA = re.compile(r"^\s*[\(\[][^\n]*[\)\]]\s*$", re.MULTILINE)
# Notas internas dentro de una línea: "... (nota: falta el peso)"
_NOTA_EN_LINEA = re.compile(
    r"\s*[\(\[]\s*(esperando|esperar|nota|interno|pendiente|accion|acción|"
    r"llamar a|herramienta|sistema)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def limpiar_respuesta_llm(texto: Optional[str]) -> Optional[str]:
    """Quita notas internas que el LLM a veces escribe para sí mismo."""
    if not texto:
        return texto
    limpio = _LINEA_NOTA.sub("", texto)
    limpio = _NOTA_EN_LINEA.sub("", limpio)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)
    return limpio.strip() or None


# ---------------- Revisión de salida (capa 2) ----------------

# Las respuestas libres deben ser cortas (el prompt pide 2-3 oraciones).
LARGO_MAXIMO_RESPUESTA = 700
_CODIGO = re.compile(
    r"```|`[^`\n]+`|^\s*(def |import |from \w+ import|print\(|for \w+ in |class \w+)",
    re.MULTILINE,
)
_ENLACE = re.compile(r"https?://|www\.", re.IGNORECASE)
# Direcciones de calle: Globix solo puede dar la dirección aprobada (FAQ), nunca una inventada
_DIRECCION = re.compile(
    r"\b(av|avda|avenida|jr|jir[oó]n|calle|ca|psje|pasaje|carretera|urb)\.?\s+[^\n,.;]{2,40}?\s\d{2,5}\b"
    r"|\b(suite|oficina|of\.|dpto|interior|int\.)\s*\d+|\b\d{3,5}\s+(nw|ne|sw|se)\b",
    re.IGNORECASE,
)
# Montos en dólares: "$640", "640 USD", "640 dólares"
_MONTO = re.compile(
    r"\$\s?(\d+(?:[.,]\d+)*)|(\d+(?:[.,]\d+)*)\s?(?:usd|d[oó]lares)\b", re.IGNORECASE
)


def revisar_respuesta_libre(
    texto: Optional[str], textos_cliente: Iterable[str], montos_permitidos: Iterable[float] = ()
) -> Optional[str]:
    """Revisa una respuesta libre del LLM antes de enviarla.

    Devuelve el motivo del bloqueo ("codigo", "enlace", "direccion", "muy_larga",
    "monto_no_dado") o None si la respuesta puede enviarse. No aplica a los
    textos armados por código (cotización, FAQ, derivaciones).
    `montos_permitidos` son montos que el propio sistema usa en ejemplos
    (p. ej. "Laptop Lenovo, USD 650, 2.5 kg"), que no cuentan como inventados.
    """
    if not texto:
        return None
    if _CODIGO.search(texto):
        return "codigo"
    if _ENLACE.search(texto):
        return "enlace"
    if _DIRECCION.search(texto):
        return "direccion"
    if len(texto) > LARGO_MAXIMO_RESPUESTA:
        return "muy_larga"
    numeros_cliente = numeros_en_texto(textos_cliente) + [float(m) for m in montos_permitidos]
    for m in _MONTO.finditer(texto):
        token = m.group(1) or m.group(2)
        if not any(_cerca(v, n) for v in _interpretar_numero(token) for n in numeros_cliente):
            return "monto_no_dado"
    return None


# ------------------------------------------------- KPI: pedir un dato indispensable

# Definición del E3 (y de H1 del E4): cuenta como primera atención útil una respuesta
# que atiende la consulta O que solicita información específica para avanzar.
# Aquí se reconoce la segunda: una pregunta o pedido por el producto, el precio,
# el peso o el código de seguimiento. Un saludo, el menú o pedir el nombre no cuentan.
_DATOS_INDISPENSABLES = re.compile(
    r"\b(pes[ao]s?|kg|kilos?|precio|cuesta|valor|usd|dolares|producto|articulo"
    r"|tracking|codigo de (seguimiento|rastreo)|numero de (seguimiento|rastreo))\b"
)
_PEDIDO = re.compile(
    r"^\s*(cuentame|indicame|dime|enviame|compart[ei]me|confirmame|pasame|escribeme)\b|\bnecesit(o|amos) (tu|el|la|saber)\b"
)
_FRASE = re.compile(r"[^.!?\n]*[.!?\n]?")


def pide_dato_indispensable(texto: Optional[str]) -> bool:
    """True si el mensaje pide al cliente un dato necesario para cotizar o rastrear."""
    if not texto:
        return False
    for frase in _FRASE.findall(_sin_tildes(texto).lower()):
        frase = re.sub(r"^[^a-z0-9]+", "", frase)  # quita "¡Claro! 😊" y signos iniciales
        if not frase:
            continue
        es_pedido = frase.rstrip().endswith("?") or _PEDIDO.search(frase)
        if es_pedido and _DATOS_INDISPENSABLES.search(frase):
            return True
    return False


# ---------------- Pedidos de varios productos (14/11) ----------------

MAX_PRODUCTOS = 10


def validar_productos(
    args: dict, textos_cliente: Iterable[str], pesos_referenciales: Iterable[float] = ()
) -> Union[Tuple[list, Optional[float]], str]:
    """Valida los productos que el LLM pasa a calcular_cotizacion.

    Acepta `productos` (lista) o, por compatibilidad, los campos de un solo producto en `args`.
    Cada precio, cantidad, peso y TAX se ancla al texto del cliente con las mismas reglas de
    siempre. Devuelve (productos para el motor, peso_total_kg o None) o el motivo del rechazo.
    """
    textos = list(textos_cliente)
    pesos_ref = list(pesos_referenciales)
    brutos = args.get("productos")
    if not brutos:
        brutos = [{"producto": args.get("producto"), "precio_unitario_usd": args.get("valor_producto_usd"),
                   "cantidad": args.get("cantidad"), "peso_kg": args.get("peso_kg"),
                   "tax_tienda_usd": args.get("tax_tienda_usd"), "sin_tax": args.get("sin_tax")}]
    if not isinstance(brutos, list) or len(brutos) > MAX_PRODUCTOS:
        return f"Pasa entre 1 y {MAX_PRODUCTOS} productos en la lista 'productos'."

    peso_total = _a_numero(args.get("peso_total_kg"))
    if args.get("peso_total_kg") is not None and (peso_total is None or peso_total <= 0):
        return "El peso total debe ser un número mayor a cero, en kg."

    salida = []
    for i, b in enumerate(brutos, 1):
        if not isinstance(b, dict):
            return "Cada producto debe ser un objeto con su precio y su peso."
        etiqueta = f"Producto {i}" + (f" ({b.get('producto')})" if b.get("producto") else "")
        legado = {"valor_producto_usd": b.get("precio_unitario_usd", b.get("valor_producto_usd")),
                  "cantidad": b.get("cantidad"), "tax_tienda_usd": b.get("tax_tienda_usd"),
                  "sin_tax": b.get("sin_tax")}
        cantidad = validar_cantidad(legado, textos)
        if isinstance(cantidad, str):
            return f"{etiqueta}: {cantidad}"
        peso_item = b.get("peso_kg")
        if peso_item is None and peso_total is None:
            return (f"{etiqueta}: falta su peso. Pide el peso de cada producto o el peso total del pedido "
                    "(peso_total_kg), o usa consultar_peso_producto.")
        legado["peso_kg"] = peso_item if peso_item is not None else peso_total
        validacion = validar_argumentos_cotizacion(legado, textos, pesos_ref, cantidad)
        if isinstance(validacion, str):
            return f"{etiqueta}: {validacion}"
        valor, peso = validacion
        tax = validar_tax_tienda(legado, textos)
        if isinstance(tax, str):
            return f"{etiqueta}: {tax}"
        salida.append({"producto": (str(b.get("producto") or "").strip()[:40] or None),
                       "tienda": (str(b.get("tienda") or "").strip()[:30] or None),
                       "precio_unitario": valor, "cantidad": cantidad,
                       "peso_kg": peso if peso_item is not None else None, "tax": tax})
    if peso_total is None and any(p["peso_kg"] is None for p in salida):
        return "Falta el peso de algún producto."
    return salida, peso_total


def validar_datos_parciales(
    args: dict, textos_cliente: Iterable[str], pesos_referenciales: Iterable[float] = ()
) -> Union[Tuple[list, Optional[float]], str]:
    """Valida un pedido incompleto (para el borrador): cada dato que venga se ancla al texto del
    cliente con las mismas reglas que al cotizar; los que falten quedan en None.

    Devuelve (líneas, peso_total_kg o None) o el motivo del rechazo.
    """
    textos = list(textos_cliente)
    pesos_ref = list(pesos_referenciales)
    brutos = args.get("productos")
    if not isinstance(brutos, list) or not 1 <= len(brutos) <= MAX_PRODUCTOS:
        return f"Pasa entre 1 y {MAX_PRODUCTOS} productos en la lista 'productos'."
    numeros = numeros_en_texto(textos)
    peso_total = _a_numero(args.get("peso_total_kg"))
    if args.get("peso_total_kg") is not None:
        if peso_total is None or peso_total <= 0:
            return "El peso total debe ser un número mayor a cero, en kg."
        if not any(_cerca(peso_total, n * f) for n in numeros for f in _FACTORES_A_KG) and \
                not any(_cerca(peso_total, p) for p in pesos_ref):
            return f"El peso total {peso_total} kg no aparece en los mensajes del cliente."

    salida = []
    for i, b in enumerate(brutos, 1):
        if not isinstance(b, dict):
            return "Cada producto debe ser un objeto."
        etiqueta = f"Producto {i}" + (f" ({b.get('producto')})" if b.get("producto") else "")
        legado = {"valor_producto_usd": b.get("precio_unitario_usd"), "cantidad": b.get("cantidad"),
                  "tax_tienda_usd": b.get("tax_tienda_usd"), "sin_tax": b.get("sin_tax")}
        cantidad = validar_cantidad(legado, textos)
        if isinstance(cantidad, str):
            return f"{etiqueta}: {cantidad}"
        precio = None
        if b.get("precio_unitario_usd") is not None:
            precio = _a_numero(b.get("precio_unitario_usd"))
            if precio is None or precio <= 0:
                return f"{etiqueta}: el precio debe ser un número mayor a cero."
            if not any(_cerca(precio, n) for n in numeros):
                return f"{etiqueta}: el precio {precio} USD no aparece en los mensajes del cliente. No lo supongas."
        peso = None
        if b.get("peso_kg") is not None:
            peso = _a_numero(b.get("peso_kg"))
            if peso is None or peso <= 0:
                return f"{etiqueta}: el peso debe ser un número mayor a cero."
            del_cliente = any(_cerca(peso, n * f * v) for n in numeros for f in _FACTORES_A_KG
                              for v in {1, cantidad})
            if not (del_cliente or any(_cerca(peso, p) for p in pesos_ref)):
                return f"{etiqueta}: el peso {peso} kg no aparece en los mensajes del cliente ni en el catálogo."
        tax = validar_tax_tienda(legado, textos) if precio is not None else None
        if isinstance(tax, str):
            return f"{etiqueta}: {tax}"
        salida.append({"producto": (str(b.get("producto") or "").strip()[:40] or None),
                       "tienda": (str(b.get("tienda") or "").strip()[:30] or None),
                       "precio_unitario": precio, "cantidad": cantidad, "peso_kg": peso, "tax": tax})
    return salida, peso_total
