"""Auto-nudge de 20 minutos: un solo recordatorio, sin casillero y marcado como automático."""

import asyncio
from datetime import timedelta

import database
import main


def _lead(chat_id, minutos_silencio, *, cotizacion=836.33, bot_activo=1, estado="Atendido por Bot"):
    database.registrar_mensaje_entrante(chat_id, "Perfil", "hola")
    hace = database.ahora() - timedelta(minutes=minutos_silencio)
    with database.get_connection() as conn:
        conn.execute(
            """UPDATE chats SET ultimo_mensaje_cliente_at = ?, cotizacion_total = ?,
               bot_activo = ?, estado = ?, recordatorio_enviado = 0 WHERE chat_id = ?""",
            (hace, cotizacion, bot_activo, estado, chat_id),
        )
        conn.commit()


def _textos(enviados):
    return [p["text"]["body"] for p in enviados if p.get("type") == "text"]


def test_envia_un_solo_recordatorio_tras_20_min(bloquear_meta):
    _lead("nudge-1", 25)
    assert asyncio.run(main.enviar_recordatorios_pendientes()) == 1
    assert asyncio.run(main.enviar_recordatorios_pendientes()) == 0  # no se repite

    textos = _textos(bloquear_meta)
    assert len(textos) == 1
    assert "USD 836.33" in textos[0] and "casillero" not in textos[0].lower()

    ultimo = database.obtener_mensajes_chat("nudge-1")[-1]
    assert ultimo["emisor"] == main.EMISOR_RECORDATORIO
    assert "recordatorio" in ultimo["emisor"]  # el dashboard lo rotula como automático


def test_no_envia_antes_de_20_min_ni_sin_cotizacion_ni_con_asesor(bloquear_meta):
    _lead("nudge-pronto", 5)
    _lead("nudge-sin-cot", 30, cotizacion=0)
    _lead("nudge-asesor", 30, bot_activo=0)
    _lead("nudge-derivado", 30, estado="Derivado a Asesor")
    assert asyncio.run(main.enviar_recordatorios_pendientes()) == 0
    assert _textos(bloquear_meta) == []


def test_si_falla_el_envio_no_registra_ni_reintenta(monkeypatch, bloquear_meta):
    async def falla(payload):
        return False

    monkeypatch.setattr(main, "_post_meta", falla)
    _lead("nudge-falla", 25)
    assert asyncio.run(main.enviar_recordatorios_pendientes()) == 0
    assert asyncio.run(main.enviar_recordatorios_pendientes()) == 0
    emisores = [m["emisor"] for m in database.obtener_mensajes_chat("nudge-falla")]
    assert main.EMISOR_RECORDATORIO not in emisores
