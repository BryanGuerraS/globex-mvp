"""Base de conocimiento comercial oficial de Globex Courier.

Fichas KB01 a KB08 aprobadas según el Manual Funcional y Operativo.
Actualizadas el 13/11/2026 con las respuestas de Juan Carlos (A4, A7, A8, A13, A14) y los flyers
oficiales de Shalom (assets/flyers/): recojo en Lima, solo Shalom, 5 días hábiles, pago por transferencia.
"""

import unicodedata
from typing import Dict, Optional

KB_GLOBEX = {
    "direccion_miami": {
        "titulo": "Plantilla de Dirección de Casillero en Miami (F21)",
        "contenido": (
            "📍 *Dirección de nuestro almacén en Miami:*\n\n"
            "• *Nombre (obligatorio):* GX / tu nombre y apellido\n"
            "• *Address Line 1:* 7270 NW 35th Terrace\n"
            "• *Address Line 2:* Suite 101\n"
            "• *City:* Miami\n"
            "• *State:* FL (Florida)\n"
            "• *Zip Code:* 33122\n"
            "• *Phone:* +1 (786) 628-8807\n"
            "• *Country:* United States\n\n"
            "⚠️ *Importante:* pon GX junto a tu nombre y apellido reales. No necesitas un código personal."
        ),
    },
    "plazos_entrega": {
        "titulo": "Tiempos y Plazos de Envío (F19 / F20)",
        "contenido": (
            "⏱️ *Plazos de entrega regulares:*\n"
            "• El tiempo estimado es de *5 días hábiles* contados a partir de que tu paquete es *recibido en nuestro almacén de Miami* (no desde que compras en la tienda).\n"
            "• Para envíos a provincias de Perú, se suman de 24 a 48 horas adicionales para el traslado por agencia."
        ),
    },
    "entrega_lima": {
        "titulo": "Entregas en Lima: recojo en oficina y delivery (A4 / A8)",
        "contenido": (
            "🏢 *Entregas en Lima:*\n"
            "• *Recojo en oficina:* Jr. Maracaibo N.º 2016. Horario: 9:00 a. m. a 6:00 p. m. "
            "(refrigerio de 1:00 a 2:00 p. m.).\n"
            "• *Delivery a domicilio:* disponible en Lima. La tarifa depende de la zona y del horario, "
            "y la coordina un asesor cuando tu paquete llega a nuestro almacén de Lima."
        ),
    },
    "cobertura_provincias": {
        "titulo": "Envíos a Provincias de Perú por Shalom (F26 / A6 / A7, flyers oficiales)",
        "contenido": (
            "🇵🇪 *Envíos a provincias:*\n"
            "• Enviamos a todo el Perú *solo por agencia Shalom*, con recojo en la agencia que elijas.\n"
            "• *Traslado a la agencia* (incluye traslado desde nuestro almacén, rotulado, embalado básico "
            "y gestión del despacho): hasta 4 kg, S/ 12.00; más de 5 kg hasta 15 kg, S/ 20.00; "
            "más de 15 kg hasta 25 kg, S/ 30.00; más de 25 kg, se coordina con un asesor.\n"
            "• El servicio de Shalom se paga en destino (contraentrega).\n"
            "• Para el envío necesitamos tu DNI, nombre completo, celular y el *nombre exacto* de la agencia Shalom."
        ),
    },
    "como_funciona": {
        "titulo": "Cómo Funciona el Servicio de Importación (F01 / F02)",
        "contenido": (
            "📦 *Cómo importar con Globex en 4 pasos:*\n"
            "1. Compras en tu tienda favorita de USA (Amazon, eBay, etc.) usando la dirección de nuestro almacén en Miami, con *GX* junto a tu nombre.\n"
            "2. Nos compartes tu código de tracking de la tienda.\n"
            "3. Recibimos tu paquete en Miami y lo transportamos en vuelo a Perú.\n"
            "4. Te notificamos a su llegada, liquidas el flete y te lo entregamos en tu casa o agencia."
        ),
    },
    # Reglas de productos y tarifa: propuestas por Claude el 16/11 tras el banco de desarrollo de 137
    # (preguntas sin respuesta aprobada); el usuario pidió aplicarlas el 16/11.
    "reglas_productos": {
        "titulo": "Reglas para productos: solo nuevos, máximos, receta y no admitidos (lista de Diego)",
        "contenido": (
            "📦 *Reglas para algunos productos:*\n"
            "• *Solo nuevos:* ropa, juguetes y repuestos de autos. Si están nuevos, cumplen; usados o de segunda "
            "mano no se pueden traer.\n"
            "• *Máximos:* perfumes 4 y maquillaje 4 por DNI; cremas 3 por DNI (la marca no cambia el máximo); "
            "calzado 5 pares y juguetes 4 por consignatario (las figuras de colección pueden pasar de 4); shampoo "
            "y productos para el cabello 2 por cotización.\n"
            "• *Con receta médica visada:* medicinas, vitaminas, proteínas y suplementos; un asesor la valida "
            "antes de cotizar.\n"
            "• *No admitidos:* armas, municiones, TV Box, artículos médicos, chupones, biberones y pegamento de "
            "pestañas."
        ),
    },
    "tarifas": {
        "titulo": "Tarifa del courier: USD 9 por kg, mínimo 1 kg, desaduanaje USD 9",
        "contenido": (
            "✈️ *Tarifa del courier:* USD 9 por kg, con un mínimo de 1 kg facturable; sobre 1 kg se cobra el "
            "peso exacto, sin redondear al kilo. El desaduanaje es USD 9 por cotización. Se cobra el peso que "
            "mide el almacén de Miami, con embalaje. Si me das el producto, su precio y su peso, te doy el "
            "total 😊"
        ),
    },
    "metodos_pago": {
        "titulo": "Formas de Pago y Liquidación (F10 / F11)",
        "contenido": (
            "💳 *Formas de pago:*\n"
            "• El producto lo compras y lo pagas tú directamente en la tienda.\n"
            "• El servicio de Globex (flete y desaduanaje) se paga por *transferencia bancaria o interbancaria*, "
            "en dólares (USD) o en soles (PEN) al tipo de cambio del día.\n"
            "• Las cuentas y el detalle del pago te los da un asesor cuando tu paquete llega a nuestro almacén, "
            "antes de la entrega final."
        ),
    },
}


# Temas que el LLM pasa a 'consultar_faq_comercial' -> ficha
TEMAS_FAQ = {
    "direccion_miami": "direccion_miami",
    "plazos_entrega": "plazos_entrega",
    "plazos": "plazos_entrega",
    "provincias": "cobertura_provincias",
    "entrega_lima": "entrega_lima",
    "lima": "entrega_lima",
    "como_funciona": "como_funciona",
    "pagos": "metodos_pago",
    "reglas_productos": "reglas_productos",
    "productos": "reglas_productos",
    "tarifas": "tarifas",
    "tarifa": "tarifas",
}


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con '_' como espacio: 'Cómo_compro' -> 'como compro'."""
    sin_tildes = unicodedata.normalize("NFD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return sin_tildes.replace("_", " ")


def buscar_faq_por_tema(tema: str) -> Optional[Dict[str, str]]:
    clave = TEMAS_FAQ.get(str(tema or "").strip().lower())
    return KB_GLOBEX[clave] if clave else None


def buscar_faq_comercial(consulta: str) -> Optional[Dict[str, str]]:
    """Busca en las fichas aprobadas de Globex según la intención del cliente."""
    texto = _normalizar(consulta)

    if any(p in texto for p in ["direccion", "dirección", "casillero", "zip", "miami", "donde envio", "dónde envío"]):
        return KB_GLOBEX["direccion_miami"]

    if any(p in texto for p in ["demora", "tarda", "plazo", "dias", "días", "tiempo de entrega", "cuanto tiempo"]):
        return KB_GLOBEX["plazos_entrega"]

    if any(p in texto for p in ["provincia", "departamento", "arequipa", "trujillo", "chiclayo", "cusco", "piura",
                                "shalom", "olva", "agencia"]):
        return KB_GLOBEX["cobertura_provincias"]

    if any(p in texto for p in ["lima", "recojo", "recoger", "oficina", "delivery", "domicilio"]):
        return KB_GLOBEX["entrega_lima"]

    if any(p in texto for p in ["como funciona", "cómo funciona", "como compro", "pasos", "primera vez", "que hace globex", "qué hace globex"]):
        return KB_GLOBEX["como_funciona"]

    if any(p in texto for p in ["pago", "pagar", "soles", "dolares", "dólares", "tarjeta", "transferencia", "yape", "plin"]):
        return KB_GLOBEX["metodos_pago"]

    return None