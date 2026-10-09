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
            "⚠️ *Mercancía Restringida por DIGEMID:*\n\n"
            "Los productos cosméticos, perfumes, vitaminas o medicamentos requieren *autorización sanitaria de DIGEMID* en la aduana de Perú.\n\n"
            "He transferido tu caso a tu asesor asignado para verificar las cantidades permitidas y los requisitos de importación antes de cotizar."
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
            "⛔ *Mercancía Prohibida de Importación:*\n\n"
            "Por regulaciones aduaneras de SUNAT y seguridad aérea internacional, Globex *no transporta* vapeadores, cigarrillos electrónicos, armas, pirotecnia ni artículos inflamables.\n\n"
            "No es posible cotizar ni trasladar este producto."
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
            "🔋 *Restricción de Baterías de Litio:*\n\n"
            "Las baterías sueltas o powerbanks tienen restricciones estrictas de transporte aéreo internacional.\n\n"
            "Un asesor revisará las especificaciones técnicas de tu producto para confirmarte si es admisible en vuelo."
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