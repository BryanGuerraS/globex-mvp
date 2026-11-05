"""Resumen del caso y aviso al asesor cuando Globix deriva (hallazgo 5)."""

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
import notificaciones
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call


@pytest.fixture
def turno(monkeypatch, bloquear_meta):
    def correr(chat_id, texto, respuestas):
        main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, "Cliente", texto))
        return main.obtener_chat(chat_id)

    return correr


@pytest.fixture
def avisos(monkeypatch):
    enviados = []

    async def telegram_falso(texto):
        enviados.append(texto)
        return True

    monkeypatch.setattr(main, "notificaciones_activas", lambda: True)
    monkeypatch.setattr(main, "enviar_telegram", telegram_falso)
    return enviados


def _cotizar(turno, chat_id):
    turno(chat_id, "zapatillas nike de 120 dólares, 1.5 kg",
          [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion",
                                             {"valor_producto_usd": 120, "peso_kg": 1.5, "producto": "Zapatillas Nike"})])])


def test_derivacion_tras_cotizar_guarda_resumen_completo(turno):
    _cotizar(turno, "PE.d1")
    chat = turno("PE.d1", "quiero hablar con un asesor",
                 [_respuesta(tool_calls=[_tool_call("t2", "derivar_a_asesor", {"motivo": "pide asesor"})])])
    assert chat["motivo_derivacion"] == "asesor" and chat["derivado_at"]
    r = chat["resumen_caso"]
    assert "Pidió hablar con un asesor" in r
    assert "Zapatillas Nike, USD 120.00, 1.5 kg, total USD" in r
    assert "Aún no dio su nombre" in r
    assert "• quiero hablar con un asesor" in r and "• zapatillas nike de 120 dólares, 1.5 kg" in r


def test_tope_y_seguimiento_tienen_su_motivo(turno):
    chat = turno("PE.d2", "laptop de 1500 dólares, 2 kg",
                 [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 1500, "peso_kg": 2})])])
    assert chat["motivo_derivacion"] == "tope" and "más de USD 1,200" in chat["resumen_caso"]
    chat = turno("PE.d3", "¿dónde está mi paquete? 1Z999",
                 [_respuesta(tool_calls=[_tool_call("t1", "clasificar_como_seguimiento", {"codigo_tracking": "1Z999"})])])
    assert chat["motivo_derivacion"] == "seguimiento"


def test_mercancia_restringida(turno):
    chat = turno("PE.d4", "quiero traer 3 perfumes por $150", [])
    assert chat["motivo_derivacion"] == "restringido"
    assert "DIGEMID" in chat["resumen_caso"]


def test_prohibida_no_se_deriva(turno):
    chat = turno("PE.d5", "quiero importar unos vapes", [])
    assert chat["motivo_derivacion"] is None


def test_aviso_por_telegram(turno, avisos):
    _cotizar(turno, "PE.d6")
    turno("PE.d6", "quiero un asesor", [_respuesta(tool_calls=[_tool_call("t2", "derivar_a_asesor", {})])])
    assert len(avisos) == 1
    assert avisos[0].startswith("🔔 *Nuevo caso para asesor*")
    assert "Zapatillas Nike" in avisos[0]


def test_sin_configuracion_no_hay_aviso(turno, monkeypatch):
    llamados = []

    async def no_deberia(texto):
        llamados.append(texto)
        return True

    monkeypatch.setattr(main, "enviar_telegram", no_deberia)
    turno("PE.d7", "quiero un asesor", [_respuesta(tool_calls=[_tool_call("t1", "derivar_a_asesor", {})])])
    assert llamados == []
    assert asyncio.run(notificaciones.enviar_telegram("x")) is False  # sin token no sale nada


# ---------- Nombre: el resumen se actualiza ----------

def _post_firmado(cliente, payload):
    cuerpo = json.dumps(payload).encode()
    firma = "sha256=" + hmac.new(b"secreto_de_prueba", cuerpo, hashlib.sha256).hexdigest()
    return cliente.post("/meta-webhook", content=cuerpo, headers={"X-Hub-Signature-256": firma})


def _payload(bsuid, wamid, mensaje):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "Cliente"}, "user_id": bsuid, "wa_id": bsuid}],
        "messages": [{"from": bsuid, "id": wamid, "timestamp": str(int(time.time())), **mensaje}],
    }}]}]}


def test_boton_asesor_y_nombre_actualizan_resumen(monkeypatch, bloquear_meta, avisos):
    monkeypatch.setattr(main, "debounce_mensajes", lambda *a: asyncio.sleep(0))
    cliente = TestClient(main.app)
    boton = {"type": "interactive", "interactive": {"type": "button_reply",
                                                     "button_reply": {"id": "asesor", "title": "Hablar con asesor"}}}
    _post_firmado(cliente, _payload("PE.d8", "wamid.d8a", boton))
    chat = main.obtener_chat("PE.d8")
    derivado_at = chat["derivado_at"]
    assert chat["motivo_derivacion"] == "asesor" and "Aún no dio su nombre" in chat["resumen_caso"]

    _post_firmado(cliente, _payload("PE.d8", "wamid.d8b", {"type": "text", "text": {"body": "Me llamo Ana Pérez"}}))
    chat = main.obtener_chat("PE.d8")
    assert "*Cliente:* Ana Pérez" in chat["resumen_caso"]
    assert chat["derivado_at"] == derivado_at  # no cuenta como derivación nueva
    assert len(avisos) == 1  # el nombre no genera un segundo aviso
