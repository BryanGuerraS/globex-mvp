"""Guardrail de elegibilidad y mercancía restringida para Globex Courier.

Alineado con las fichas F28, F30, F31 y casuísticas CE11, CE12 de SUNAT/DIGEMID.
"""

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


def verificar_mercancia_restringida(texto: str) -> Optional[Dict[str, str]]:
    """Analiza si el texto menciona algún producto prohibido o restringido."""
    texto_lower = texto.lower()

    for tipo, datos in RESTRICCIONES_ADUANA.items():
        for palabra in datos["palabras"]:
            # Búsqueda exacta de palabra
            if palabra in texto_lower:
                return {
                    "restringido": True,
                    "tipo": tipo,
                    "entidad": datos["entidad"],
                    "mensaje": datos["mensaje"],
                    "palabra_detectada": palabra,
                }

    return None