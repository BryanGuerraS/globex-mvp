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
            "municion",
            "semilla",
            "semillas",
            "pirotecnia",
            "spray",
            "chupon",
            "biberon",
            "pegamento de pestanas",
            "pegamento para pestanas",
        ],
        "entidad": "PROHIBICIÓN ABSOLUTA",
        "mensaje": (
            "⛔ Globex *no transporta* vapeadores, cigarrillos electrónicos, armas, municiones, pirotecnia, "
            "semillas, sprays, artículos inflamables, chupones, biberones ni pegamento de pestañas (normas de SUNAT, de seguridad "
            "aérea y de Globex). Si quieres traer otro producto, con gusto lo cotizo."
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
            "the ordinary",
        ],
        "entidad": "LÍMITE POR DNI",
        "mensaje": (
            "⚠️ Los perfumes, el maquillaje y las cremas tienen un *máximo por DNI*. "
            "Un asesor revisará las cantidades de tu caso y te escribirá por este chat antes de cotizar."
        ),
        # Solo si el cliente pregunta por los máximos (cuántos, límite...)
        "mensaje_detalle": (
            "⚠️ Estos productos tienen un *máximo por DNI*:\n"
            "• Perfumes: 4\n"
            "• Maquillaje: 4\n"
            "• Cremas: 3\n"
            "• The Ordinary: 4\n"
            "Por guía no se pueden juntar más de 4 productos restringidos en total. "
            "Un asesor revisará tu caso y te escribirá por este chat antes de cotizar."
        ),
    },
    "restringido": {
        "palabras": [
            "tv box",
            "articulo medico",
            "articulos medicos",
            "equipo medico",
            "equipos medicos",
        ],
        "entidad": "RESTRINGIDO",
        "mensaje": (
            "⚠️ Ese producto tiene restricciones para importarse. "
            "Un asesor revisará tu caso y te escribirá por este chat antes de cotizar."
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

# Productos que solo entran nuevos: se informa y el bot sigue atendiendo (no se deriva)
_PRODUCTO_SOLO_NUEVO = r"(?:ropa|prendas?|polos?|repuestos?|autopartes?|juguetes?)"
_USADO = r"(?:usad[oa]s?|de segunda(?: mano)?|seminuev[oa]s?)"
_SOLO_NUEVOS = re.compile(
    rf"(?<![a-z0-9]){_PRODUCTO_SOLO_NUEVO}(?![a-z0-9])(?:\W+\w+){{0,4}}?\W+{_USADO}(?![a-z0-9])"
    rf"|(?<![a-z0-9]){_USADO}(?:\W+\w+){{0,3}}?\W+{_PRODUCTO_SOLO_NUEVO}(?![a-z0-9])"
)
SOLO_NUEVOS = {
    "entidad": "SOLO NUEVOS",
    "mensaje": (
        "⚠️ La ropa, los juguetes y los repuestos de autos solo pueden ingresar a Perú si son *nuevos*. "
        "Si tu producto es nuevo, cuéntame su precio en USD y su peso en kg y lo cotizo."
    ),
}

# Máximo por DNI de productos que sí se cotizan (lista de Diego): solo se deriva si se pasa
LIMITES_POR_DNI = [
    {"nombre": "calzado", "unidad": "pares", "maximo": 5,
     "palabras": ["zapatilla", "zapato", "calzado", "sandalia", "bota"]},
    {"nombre": "juguetes nuevos", "unidad": "unidades", "maximo": 4, "palabras": ["juguete"]},
    {"nombre": "shampoo y productos para el cabello", "unidad": "unidades", "maximo": 2,
     "palabras": ["shampoo", "champu", "acondicionador"]},
]


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
_PATRONES_LIMITE = [(lim, [_patron(p) for p in lim["palabras"]]) for lim in LIMITES_POR_DNI]


def verificar_mercancia_restringida(texto: str) -> Optional[Dict[str, str]]:
    """Analiza si el texto menciona algún producto prohibido o restringido."""
    texto_normalizado = _normalizar(texto)

    for tipo, datos in RESTRICCIONES_ADUANA.items():
        for palabra, patron in _PATRONES[tipo]:
            # Búsqueda de la palabra completa (no como parte de otra palabra)
            if patron.search(texto_normalizado):
                pide_detalle = "mensaje_detalle" in datos and _PIDE_MAXIMOS.search(texto_normalizado)
                return {
                    "restringido": True,
                    "tipo": tipo,
                    "entidad": datos["entidad"],
                    "mensaje": datos["mensaje_detalle"] if pide_detalle else datos["mensaje"],
                    "palabra_detectada": palabra,
                }

    m = _SOLO_NUEVOS.search(texto_normalizado)
    if m:
        return {"restringido": True, "tipo": "solo_nuevos", **SOLO_NUEVOS, "palabra_detectada": m.group(0)}

    return None


def limite_por_dni_excedido(textos: Iterable[str], cantidad: int) -> Optional[Dict[str, str]]:
    """Si el cliente pide más unidades que el máximo por DNI de su producto, el motivo y el mensaje."""
    texto = _normalizar(" ".join(textos))
    for lim, patrones in _PATRONES_LIMITE:
        if cantidad > lim["maximo"] and any(p.search(texto) for p in patrones):
            return {
                "entidad": "LÍMITE POR DNI",
                "detalle": f"{cantidad} {lim['unidad']} de {lim['nombre']} (máximo {lim['maximo']})",
                "mensaje": (
                    f"⚠️ El máximo por DNI es de {lim['maximo']} {lim['unidad']} de {lim['nombre']}. "
                    "Un asesor revisará tu pedido y te escribirá por este chat para ver cómo traerlo."
                ),
            }
    return None
