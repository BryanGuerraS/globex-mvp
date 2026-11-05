"""Aviso inmediato a los asesores cuando Globix deriva un caso.

Canal: Telegram (gratis e inmediato). Se activa solo si están configuradas
TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID; si no, no hace nada (el caso igual
queda en el dashboard con su resumen).

Configuración (una vez):
1. En Telegram, hablar con @BotFather → /newbot → copiar el token.
2. Crear un grupo con los asesores y agregar el bot.
3. Escribir algo en el grupo y abrir https://api.telegram.org/bot<TOKEN>/getUpdates
   para ver el "chat":{"id": -100...} del grupo.
4. Poner ambos valores en Render → Environment.
"""

import os
from typing import Optional

import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")


def notificaciones_activas() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def texto_aviso(resumen: str, nombre_cliente: Optional[str] = None) -> str:
    titulo = "🔔 *Nuevo caso para asesor*"
    pie = f"\n\nAbrir consola: {DASHBOARD_URL}" if DASHBOARD_URL else ""
    return f"{titulo}\n\n{resumen}{pie}"


async def enviar_telegram(texto: str) -> bool:
    """Envía el aviso al grupo de asesores. Nunca lanza excepción."""
    if not notificaciones_activas():
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    base = {"chat_id": TELEGRAM_CHAT_ID, "text": texto, "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient() as cliente:
            res = await cliente.post(url, json={**base, "parse_mode": "Markdown"}, timeout=10.0)
            if res.status_code == 400:
                # Un "_" o "*" del cliente puede romper el Markdown: se reenvía como texto plano
                res = await cliente.post(url, json=base, timeout=10.0)
        if res.status_code == 200:
            return True
        print(f"⚠️ [Telegram] Error {res.status_code}: {res.text[:200]}")
    except Exception as e:
        print(f"❌ [Telegram] Error de conexión: {e}")
    return False
