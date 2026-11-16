"""Guardrail de elegibilidad y mercancía restringida para Globex Courier.

Alineado con las fichas F28, F30, F31 y casuísticas CE11, CE12 de SUNAT/DIGEMID, y con la lista
de restricciones que envió Diego por WhatsApp (13/11/2026): límites por DNI, receta visada,
productos que solo entran nuevos y prohibidos (chupones, biberones, pegamento de pestañas).
"""

import re
import unicodedata
from typing import Dict, Iterable, Optional

# Palabras clave de productos sensibles y su tratamiento, en orden de prioridad:
# lo prohibido gana a lo que solo se deriva.
RESTRICCIONES_ADUANA = {
    "prohibido": {
        "palabras": [
            "vape",
            "vapes",
            "vapeador",
            "pod",
            "cigarrillo electronico",
            "arma",
            "armas",
            "revolver",
            "rifle",
            "escopeta",
            "fusil",
            "municion",
            "semilla",
            "semillas",
            "pirotecnia",
            "spray",
            "chupon",
            "biberon",
            "pegamento de pestanas",
            "pegamento para pestanas",
            "pegamento para colocar pestanas",
            "adhesivo de pestanas",
            "adhesivo para pestanas",
            "adhesivo para colocar pestanas",
        ],
        "entidad": "PROHIBICIÓN ABSOLUTA",
        "mensaje": (
            "⛔ Globex *no transporta* vapeadores, cigarrillos electrónicos, armas, municiones, pirotecnia, "
            "semillas, sprays, artículos inflamables, chupones, biberones ni pegamento de pestañas (normas de SUNAT, de seguridad "
            "aérea y de Globex). Si quieres traer otro producto, con gusto lo cotizo."
        ),
    },
    "no_admitido": {
        "palabras": [
            "tv box",
            "tvbox",
            "articulo medico",
            "articulos medicos",
            "equipo medico",
            "equipos medicos",
            "dispositivo medico",
            "dispositivos medicos",
            "aparato medico",
            "aparatos medicos",
        ],
        "entidad": "NO ADMITIDO",
        "mensaje": (
            "⛔ Globex *no admite* TV Box ni artículos médicos, así que no puedo cotizarlos. "
            "Si quieres traer otro producto, con gusto te ayudo 😊"
        ),
    },
    "receta": {
        "palabras": [
            "vitamina",
            "vitaminas",
            "suplemento",
            "suplementos",
            "proteina",
            "proteína",
            "medicamento",
            "medicina",
        ],
        "entidad": "RECETA MÉDICA VISADA",
        "mensaje": (
            "⚠️ Las medicinas, vitaminas, proteínas y suplementos solo pueden ingresar a Perú con "
            "*receta médica visada*. Un asesor revisará tu caso y te escribirá por este chat antes de cotizar."
        ),
    },
    "limite_dni": {
        "palabras": [
            "perfume",
            "perfumes",
            "colonia",
            "colonias",
            "maquillaje",
            "cosmetico",
            "cosméticos",
            "crema",
            "cremas",
        ],
        "entidad": "LÍMITE POR DNI",
        # Desde el 15/11 (decisión del usuario) se cotizan dentro del máximo: el guardrail solo
        # responde si el cliente pregunta por los máximos; el máximo se revisa al cotizar.
        "solo_si_pregunta": True,
        "mensaje_detalle": (
            "⚠️ Estos productos tienen un *máximo por DNI*:\n"
            "• Perfumes: 4\n"
            "• Maquillaje: 4\n"
            "• Cremas: 3\n"
            "Si tu pedido está dentro del máximo, cuéntame el precio en USD y el peso en kg y lo cotizo 😊"
        ),
    },
    "baterias": {
        "palabras": [
            "bateria suelta",
            "batería suelta",
            "powerbank",
            "baterias de litio",
        ],
        "entidad": "CARGA PELIGROSA (IATA)",
        "mensaje": (
            "🔋 Las baterías sueltas y los powerbanks tienen restricciones para viajar en avión. "
            "Un asesor revisará tu producto y te confirmará por este chat si se puede enviar."
        ),
    },
}

# El cliente pregunta por los máximos: se le da el detalle por producto
_PIDE_MAXIMOS = re.compile(r"(?<![a-z])(?:cuant[oa]s|maxim[oa]s?|limites?|cantidad(?:es)?|cupo)(?![a-z])")

# Productos que solo entran nuevos: se informa, no se cotiza el usado y el bot sigue atendiendo
# (no se deriva). Texto aprobado por el usuario el 15/11 (ya no ofrece cotizar).
_PRODUCTO_SOLO_NUEVO = (r"(?:ropa|prendas?|polos?|camisas?|camisetas?|chaquetas?|casacas?|pantalon(?:es)?|"
                        r"vestidos?|polera|poleras|blusas?|abrigos?|repuestos?|autopartes?|juguetes?)")
_USADO = (r"(?:usad[oa]s?|utilizad[oa]s?|de segunda(?: mano)?|seminuev[oa]s?|"
          r"ya (?:(?:las?|los?|lo|la) )?(?:use|uso|usaron|usamos|utilice|utilizo|utilizaron|utilizamos))")
_SOLO_NUEVOS = re.compile(
    rf"(?<![a-z0-9]){_PRODUCTO_SOLO_NUEVO}(?![a-z0-9])(?:\W+\w+){{0,10}}?\W+{_USADO}(?![a-z0-9])"
    rf"|(?<![a-z0-9]){_USADO}(?:\W+\w+){{0,4}}?\W+{_PRODUCTO_SOLO_NUEVO}(?![a-z0-9])"
)
SOLO_NUEVOS = {
    "entidad": "SOLO NUEVOS",
    "mensaje": (
        "⚠️ La ropa, los juguetes y los repuestos de autos solo pueden ingresar a Perú si son *nuevos*, "
        "así que no puedo cotizar productos usados. Si quieres traer otro producto, con gusto te ayudo 😊"
    ),
}

# Máximos por categoría como datos (guía §3.4): unidad y ámbito de cada uno. Se revisan con la
# cantidad de cada producto al cotizar; solo se deriva si se pasa (15/11: también perfumes,
# maquillaje y cremas). El mensaje dice el ámbito: "por DNI", "por consignatario" o "por cotización".
LIMITES_POR_DNI = [
    {"nombre": "calzado", "unidad": "pares", "maximo": 5, "ambito": "consignatario",
     "palabras": ["zapatilla", "zapato", "calzado", "sandalia", "bota"]},
    {"nombre": "juguetes nuevos", "unidad": "unidades", "maximo": 4, "ambito": "consignatario",
     "palabras": ["juguete"],
     # Las figuras de colección pueden superar las 4 unidades (no se extiende a otros juguetes)
     "excepto": ["figura de coleccion", "figuras de coleccion", "figura coleccionable",
                 "figuras coleccionables"]},
    {"nombre": "shampoo y productos para el cabello", "unidad": "unidades", "maximo": 2,
     "ambito": "cotizacion", "palabras": ["shampoo", "champu", "acondicionador"]},
    {"nombre": "perfumes", "unidad": "unidades", "maximo": 4, "ambito": "dni",
     "palabras": ["perfume", "colonia"]},
    {"nombre": "maquillaje", "unidad": "unidades", "maximo": 4, "ambito": "dni",
     "palabras": ["maquillaje", "cosmetico"]},
    # La marca (The Ordinary) no sube el máximo de la categoría (guía §3.4)
    {"nombre": "cremas", "unidad": "unidades", "maximo": 3, "ambito": "dni", "palabras": ["crema"]},
]


_AMBITOS = {"dni": "DNI", "consignatario": "consignatario", "cotizacion": "cotización"}


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para que "cosméticos" y "cosmeticos" coincidan."""
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def _patron(palabra: str) -> "re.Pattern":
    # Palabra completa: "pod" no debe coincidir con "podrías" ni "iPod", ni "arma" con "armario".
    # Se acepta el plural ("medicamentos", "municiones", "vapeadores").
    return re.compile(r"(?<![a-z0-9])" + re.escape(_normalizar(palabra)) + r"(?:s|es)?(?![a-z0-9])")


_PATRONES = {
    tipo: [(palabra, _patron(palabra)) for palabra in datos["palabras"]]
    for tipo, datos in RESTRICCIONES_ADUANA.items()
}
_PATRONES_LIMITE = [(lim, [_patron(p) for p in lim["palabras"]], [_patron(p) for p in lim.get("excepto", [])])
                    for lim in LIMITES_POR_DNI]


# Mención negada (guía §3.3 y §3.7): "no es un vape", "no traigo armas", "sin pilas ni baterías sueltas".
# Se mira hasta 4 palabras antes de la coincidencia.
_NEGACION = re.compile(
    r"(?<![a-z])(?:no\s+(?:es|son|sera|seran|lleva|llevan|tiene|tienen|incluye|incluyen|contiene|contienen|"
    r"traigo|traere|traeria|voy\s+a\s+traer|quiero|necesito|compro|comprare|vendo)|sin|ni|tampoco|nada\s+de|"
    r"descarte|descartado|descartada|deje\s+de\s+lado|olvida|olvidate|ya\s+no\s+(?:quiero|voy\s+a))"
    r"(?:\s+\w+){0,3}\s*$"
)


# "ropa nueva, no usada": la negación queda dentro de la coincidencia
_USADO_NEGADO = re.compile(r"(?<![a-z])(?:nuev[oa]s?|no\s+(?:es\s+|son\s+|esta\s+|estan\s+)?(?:usad|de\s+segunda|seminuev))")


# Negación después de la mención: "el TV Box, no lo compraré", "el vape ya no lo voy a traer"
_NEGACION_DESPUES = re.compile(
    r"^\W*(?:\w+\W+){0,4}?(?:no|ya\s+no)\s+(?:lo|la|los|las)\s+(?:compro|comprare|traigo|traere|voy|quiero|pido)")


def _negada(texto: str, inicio: int, fin: Optional[int] = None) -> bool:
    if _NEGACION.search(texto[max(0, inicio - 60):inicio].rstrip(" ,")):
        return True
    return fin is not None and bool(_NEGACION_DESPUES.search(texto[fin:fin + 60]))


def verificar_mercancia_restringida(texto: str) -> Optional[Dict[str, str]]:
    """Analiza si el texto menciona algún producto prohibido o restringido."""
    texto_normalizado = _normalizar(texto)

    for tipo, datos in RESTRICCIONES_ADUANA.items():
        for palabra, patron in _PATRONES[tipo]:
            # Búsqueda de la palabra completa (no como parte de otra palabra)
            m = next((m for m in patron.finditer(texto_normalizado)
                      if not _negada(texto_normalizado, m.start(), m.end())),
                     None)
            if m:
                pide_detalle = "mensaje_detalle" in datos and _PIDE_MAXIMOS.search(texto_normalizado)
                if datos.get("solo_si_pregunta") and not pide_detalle:
                    break  # se cotiza: el máximo se revisa con la cantidad al calcular
                # Con una cantidad ("¿4 perfumes están dentro?") se responde sí o no; sin cantidad, el detalle
                concreta = (respuesta_regla(texto, revisar_alerta=False, solo_con_cantidad=True)
                            if datos.get("solo_si_pregunta") else None)
                return {
                    "restringido": True,
                    "tipo": tipo,
                    "entidad": datos["entidad"],
                    "mensaje": concreta or (datos["mensaje_detalle"] if pide_detalle else datos["mensaje"]),
                "solo_informa": bool(datos.get("solo_si_pregunta")),
                    "palabra_detectada": palabra,
                }

    m = next((m for m in _SOLO_NUEVOS.finditer(texto_normalizado)
              if not _negada(texto_normalizado, m.start()) and not _USADO_NEGADO.search(m.group(0))), None)
    if m:
        return {"restringido": True, "tipo": "solo_nuevos", **SOLO_NUEVOS, "palabra_detectada": m.group(0)}

    return None


def limite_por_dni_excedido(textos: Iterable[str], cantidad: int) -> Optional[Dict[str, str]]:
    """Si el cliente pide más unidades que el máximo por DNI de su producto, el motivo y el mensaje."""
    texto = _normalizar(" ".join(textos))
    for lim, patrones, excepciones in _PATRONES_LIMITE:
        if any(e.search(texto) for e in excepciones):
            continue
        if cantidad > lim["maximo"] and any(p.search(texto) for p in patrones):
            return {
                "entidad": "LÍMITE POR DNI",
                "detalle": f"{cantidad} {lim['unidad']} de {lim['nombre']} (máximo {lim['maximo']} por {_AMBITOS[lim['ambito']]})",
                "ambito": lim["ambito"],
                "mensaje": (
                    f"⚠️ El máximo por {_AMBITOS[lim['ambito']]} es de {lim['maximo']} {lim['unidad']} de {lim['nombre']}. "
                    "Un asesor revisará tu pedido y te escribirá por este chat para ver cómo traerlo."
                ),
            }
    return None


_CATEGORIA_SOLO_NUEVO = re.compile(rf"(?<![a-z0-9]){_PRODUCTO_SOLO_NUEVO}(?![a-z0-9])")
_DICE_NUEVO = re.compile(r"(?<![a-z])nuev[oa]s?(?![a-z])")


def es_categoria_solo_nuevos(texto: str) -> bool:
    """El producto es ropa, juguete o repuesto (categorías que solo entran nuevas)."""
    return bool(_CATEGORIA_SOLO_NUEVO.search(_normalizar(texto or "")))


def dice_que_es_nuevo(texto: str) -> bool:
    return bool(_DICE_NUEVO.search(_normalizar(texto or "")))



# ---------------------------------------------------------------------------------------------
# Respuestas armadas por código a "¿esto cumple la regla?" (16/11, opción aprobada por el usuario):
# el código compara la cantidad con el máximo de la categoría; el LLM no decide el sí o el no.

_NUM_PALABRA = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
                "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20}
_CANTIDAD = r"(\d{1,3}|" + "|".join(_NUM_PALABRA) + r")"

TEXTO_REGLA_DENTRO = ("✅ Sí: traer {n} {unidad} de {nombre} está dentro del máximo de {maximo} por {ambito}. "
                      "Si quieres, cuéntame el precio en USD y el peso en kg y lo cotizo 😊")
TEXTO_REGLA_EXCEDE = "⚠️ No: el máximo es de {maximo} {unidad} de {nombre} por {ambito}, así que {n} lo supera."
TEXTO_REGLA_MAXIMO = "📦 El máximo es de {maximo} {unidad} de {nombre} por {ambito}."
TEXTO_REGLA_COLECCION = ("✅ Sí: las figuras de colección pueden pasar de 4 unidades. El máximo de 4 por "
                         "consignatario es para los demás juguetes.")
TEXTO_REGLA_NUEVO = ("✅ Sí: la ropa, los juguetes y los repuestos de autos pueden ingresar a Perú si son "
                     "nuevos, así que tu producto cumple esa condición.")


def limite_de(texto: str) -> Optional[Dict]:
    """Máximo de la categoría del producto ({lim, excepcion}); None si la categoría no tiene máximo."""
    t = _normalizar(texto or "")
    for lim, patrones, excepciones in _PATRONES_LIMITE:
        if any(e.search(t) for e in excepciones):
            return {"lim": lim, "excepcion": True}
        if any(p.search(t) for p in patrones):
            return {"lim": lim, "excepcion": False}
    return None


def cantidad_del_producto(texto: str, lim: Dict) -> Optional[int]:
    """Cantidad escrita junto al producto ("cuatro perfumes", "6 pares de zapatos"); None si no está."""
    t = _normalizar(texto or "")
    palabras = "|".join(re.escape(_normalizar(p)) for p in lim["palabras"] + lim.get("excepto", []))
    m = re.search(rf"(?<![a-z0-9]){_CANTIDAD}\W+(?:\w+\W+){{0,3}}?(?:{palabras})", t)
    if not m:
        return None
    valor = m.group(1)
    return int(valor) if valor.isdigit() else _NUM_PALABRA[valor]


def respuesta_regla(texto: str, producto: Optional[str] = None, revisar_alerta: bool = True,
                    solo_con_cantidad: bool = False) -> Optional[str]:
    """Respuesta fija a si un producto concreto cumple una regla, o None si no hay una regla aplicable.

    `texto` es el mensaje del cliente: la cantidad y el estado se toman de ahí (anclados), no del LLM.
    """
    base = f"{producto or ''} {texto or ''}"
    alerta = ((producto and verificar_mercancia_restringida(producto)) or verificar_mercancia_restringida(texto or "")
              if revisar_alerta else None)
    if alerta and alerta["tipo"] in ("prohibido", "no_admitido", "receta", "baterias", "solo_nuevos"):
        return alerta["mensaje"]
    info = limite_de(producto or "") or limite_de(texto or "")
    if info:
        lim = info["lim"]
        if info["excepcion"]:
            return TEXTO_REGLA_COLECCION
        n = cantidad_del_producto(base, lim)
        datos = {"n": n, "unidad": lim["unidad"], "nombre": lim["nombre"], "maximo": lim["maximo"],
                 "ambito": _AMBITOS[lim["ambito"]]}
        if n is None:
            return None if solo_con_cantidad else TEXTO_REGLA_MAXIMO.format(**datos)
        return (TEXTO_REGLA_DENTRO if n <= lim["maximo"] else TEXTO_REGLA_EXCEDE).format(**datos)
    if es_categoria_solo_nuevos(base) and dice_que_es_nuevo(texto or ""):
        return TEXTO_REGLA_NUEVO
    return None
