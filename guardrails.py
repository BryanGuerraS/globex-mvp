"""Guardrail de elegibilidad y mercancía restringida para Globex Courier.

Alineado con las fichas F28, F30, F31 y casuísticas CE11, CE12 de SUNAT/DIGEMID.
"""

import re
import unicodedata
from typing import Dict, Optional

# Palabras clave de productos sensibles y su tratamiento
RESTRICCIONES_ADUANA = {
    "digemid": {
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
            "vitamina",
            "vitaminas",
            "suplemento",
            "suplementos",
            "proteina",
            "proteína",
            "medicamento",
            "medicina",
        ],
        "entidad": "DIGEMID",
        "mensaje": (
            "⚠️ Los perfumes, cosméticos, vitaminas y medicamentos necesitan *autorización de DIGEMID* para ingresar a Perú. "
            "Un asesor revisará las cantidades y requisitos de tu caso y te escribirá por este chat antes de cotizar."
        ),
    },
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
        ],
        "entidad": "PROHIBICIÓN ABSOLUTA",
        "mensaje": (
            "⛔ Por normas de SUNAT y de seguridad aérea, Globex *no transporta* vapeadores, cigarrillos electrónicos, "
            "armas, pirotecnia ni artículos inflamables. Si quieres traer otro producto, con gusto lo cotizo."
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


def verificar_mercancia_restringida(texto: str) -> Optional[Dict[str, str]]:
    """Analiza si el texto menciona algún producto prohibido o restringido."""
    texto_normalizado = _normalizar(texto)

    for tipo, datos in RESTRICCIONES_ADUANA.items():
        for palabra, patron in _PATRONES[tipo]:
            # Búsqueda de la palabra completa (no como parte de otra palabra)
            if patron.search(texto_normalizado):
                return {
                    "restringido": True,
                    "tipo": tipo,
                    "entidad": datos["entidad"],
                    "mensaje": datos["mensaje"],
                    "palabra_detectada": palabra,
                }

    return None