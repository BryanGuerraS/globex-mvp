"""Base de conocimiento comercial oficial de Globex Courier.

Fichas KB01 a KB08 aprobadas según el Manual Funcional y Operativo.
"""

from typing import Dict, Optional

KB_GLOBEX = {
    "direccion_miami": {
        "titulo": "Plantilla de Dirección de Casillero en Miami (F21)",
        "contenido": (
            "📍 *Dirección de nuestro almacén en Miami:*\n\n"
            "• *Address Line 1:* 8400 NW 25th St, Suite 100\n"
            "• *Address Line 2:* [Tu Nombre Completo] + Código GX (ej. GX-XXXX)\n"
            "• *City:* Doral / Miami\n"
            "• *State:* FL (Florida)\n"
            "• *Zip Code:* 33122\n"
            "• *Country:* United States\n\n"
            "⚠️ *Importante:* Tu código GX personal te lo asignará tu asesor al registrar tu orden."
        ),
    },
    "plazos_entrega": {
        "titulo": "Tiempos y Plazos de Envío (F19 / F20)",
        "contenido": (
            "⏱️ *Plazos de entrega regulares:*\n"
            "• El tiempo estimado es de *5 a 7 días hábiles* contados a partir de que tu paquete es *recibido en nuestro almacén de Miami* (no desde que compras en la tienda).\n"
            "• Para envíos a provincias de Perú, se suman de 24 a 48 horas adicionales para el traslado por agencia."
        ),
    },
    "cobertura_provincias": {
        "titulo": "Envíos a Provincias de Perú (F26)",
        "contenido": (
            "🇵🇪 *Cobertura a Nivel Nacional:*\n"
            "• Entregamos en Lima (recojo en oficina o delivery a domicilio).\n"
            "• Realizamos envíos a *todas las provincias del Perú* a través de agencias de confianza (Olva Courier o Shalom) con recojo en agencia o entrega en tu domicilio."
        ),
    },
    "como_funciona": {
        "titulo": "Cómo Funciona el Servicio de Importación (F01 / F02)",
        "contenido": (
            "📦 *Cómo importar con Globex en 4 pasos:*\n"
            "1. Compras en tu tienda favorita de USA (Amazon, eBay, etc.) usando la dirección de nuestro almacén en Miami.\n"
            "2. Nos compartes tu código de tracking de la tienda.\n"
            "3. Recibimos tu paquete en Miami y lo transportamos en vuelo a Perú.\n"
            "4. Te notificamos a su llegada, liquidas el flete y te lo entregamos en tu casa o agencia."
        ),
    },
    "metodos_pago": {
        "titulo": "Formas de Pago y Liquidación (F10 / F11)",
        "contenido": (
            "💳 *Métodos de pago del servicio:*\n"
            "• Puedes pagar en *Dólares (USD)* o en *Soles (PEN)* al tipo de cambio oficial del día.\n"
            "• Aceptamos transferencia bancaria (BCP, Interbank), Yape / Plin y tarjetas.\n"
            "• El costo del flete se cancela cuando tu paquete llega a Perú, antes de la entrega final."
        ),
    },
}


def buscar_faq_comercial(consulta: str) -> Optional[Dict[str, str]]:
    """Busca en las fichas aprobadas de Globex según la intención del cliente."""
    texto = consulta.lower()

    if any(p in texto for p in ["direccion", "dirección", "casillero", "zip", "miami", "donde envio", "dónde envío"]):
        return KB_GLOBEX["direccion_miami"]

    if any(p in texto for p in ["demora", "tarda", "plazo", "dias", "días", "tiempo de entrega", "cuanto tiempo"]):
        return KB_GLOBEX["plazos_entrega"]

    if any(p in texto for p in ["provincia", "departamento", "arequipa", "trujillo", "chiclayo", "cusco", "piura", "domicilio", "lima"]):
        return KB_GLOBEX["cobertura_provincias"]

    if any(p in texto for p in ["como funciona", "cómo funciona", "como compro", "pasos", "primera vez", "que hace globex", "qué hace globex"]):
        return KB_GLOBEX["como_funciona"]

    if any(p in texto for p in ["pago", "pagar", "soles", "dolares", "dólares", "tarjeta", "transferencia", "yape", "plin"]):
        return KB_GLOBEX["metodos_pago"]

    return None