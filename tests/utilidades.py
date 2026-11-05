"""Helpers de pruebas sin efectos secundarios."""


def cuerpo_de(payload):
    """Texto visible de un envío a Meta (texto o interactivo); None si es 'leído'."""
    if payload.get("type") == "text":
        return payload["text"]["body"]
    if payload.get("type") == "interactive":
        return payload["interactive"]["body"]["text"]
    return None


def mensajes_enviados(payloads):
    return [c for c in (cuerpo_de(p) for p in payloads) if c is not None]


def texto_bot_registrado(chat_id):
    """Todo lo que el bot dejó registrado en la BD para el chat (incluye el desglose de la proforma)."""
    import main
    return "\n".join(m["texto"] for m in main.obtener_mensajes_chat(chat_id) if m["emisor"].startswith("bot"))
