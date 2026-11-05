"""Pruebas de los puntos 3 y 4: mensajes atrasados e historial desde SQLite."""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call


@pytest.fixture
def turno(monkeypatch):
    """Simula un turno completo: el webhook registra el/los mensajes y luego se procesa."""
    enviados = []

    async def enviar_falso(destino, texto):
        enviados.append(texto)

    monkeypatch.setattr(main, "send_meta_whatsapp_message", enviar_falso)

    def correr(chat_id, mensajes_cliente, respuestas):
        for texto in mensajes_cliente:
            main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        asyncio.run(
            main.procesar_mensaje_consolidado(chat_id, "Cliente", " ".join(mensajes_cliente))
        )
        return llm, enviados[-1]

    return correr


def _reiniciar_servidor():
    """Lo que pasa en Render al reiniciar: se pierde toda la memoria del proceso."""
    main.sessions.clear()
    main.message_buffer.clear()


def _contenidos(mensajes, rol):
    return [m["content"] for m in mensajes if m.get("role") == rol]


# ---------- Punto 4: historial desde SQLite ----------

def test_historial_sobrevive_reinicio(turno):
    turno("h_reinicio", ["quiero traer una tv de 800 dólares"], [_respuesta(content="¿Cuánto pesa la TV?")])
    _reiniciar_servidor()
    llm, _ = turno("h_reinicio", ["pesa 9 kg"], [_respuesta(content="ok")])

    mensajes = llm.llamadas[0]
    assert _contenidos(mensajes, "user") == ["quiero traer una tv de 800 dólares", "pesa 9 kg"]
    assert "¿Cuánto pesa la TV?" in _contenidos(mensajes, "assistant")


def test_cotiza_con_datos_dados_antes_del_reinicio(turno):
    turno("h_cot", ["una tv de 800 dólares"], [_respuesta(content="¿Cuánto pesa?")])
    _reiniciar_servidor()
    llm, enviado = turno(
        "h_cot",
        ["pesa 9 kg"],
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 800, "peso_kg": 9})])],
    )
    # El valor 800 viene de un mensaje anterior al reinicio y aun así se valida.
    assert "COTIZACIÓN ESTIMADA" in enviado


def test_mensaje_del_turno_no_se_duplica(turno):
    llm, _ = turno("h_dup", ["hola", "quiero cotizar"], [_respuesta(content="¿Qué producto?")])
    usuario = _contenidos(llm.llamadas[0], "user")
    assert usuario == ["hola quiero cotizar"]


def test_incluye_mensajes_del_asesor(turno):
    turno("h_asesor", ["hola"], [_respuesta(content="¿En qué te ayudo?")])
    main.registrar_mensaje_saliente("h_asesor", "Carlos (Asesor 1)", "Te confirmo que sí enviamos a Cusco")
    llm, _ = turno("h_asesor", ["perfecto, gracias"], [_respuesta(content="¡A ti!")])
    asistente = _contenidos(llm.llamadas[0], "assistant")
    assert "[Mensaje del asesor Carlos (Asesor 1)]: Te confirmo que sí enviamos a Cusco" in asistente


def test_olvida_mensajes_de_mas_de_12_horas(turno):
    viejo = datetime.now() - timedelta(hours=main.HORAS_CONTEXTO + 1)
    main.registrar_mensaje_entrante("h_viejo", "Cliente", "x")
    with main.get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, emisor, texto, timestamp) VALUES (?, 'cliente', ?, ?)",
            ("h_viejo", "mensaje de ayer", viejo),
        )
        conn.execute("DELETE FROM messages WHERE chat_id = 'h_viejo' AND texto = 'x'")
        conn.commit()
    llm, _ = turno("h_viejo", ["hola de nuevo"], [_respuesta(content="¡Hola!")])
    assert "mensaje de ayer" not in _contenidos(llm.llamadas[0], "user")


def test_limite_de_mensajes_en_contexto(turno):
    for i in range(main.MAX_MENSAJES_CONTEXTO + 10):
        main.registrar_mensaje_saliente("h_largo", "bot", f"respuesta {i}")
    llm, _ = turno("h_largo", ["hola"], [_respuesta(content="ok")])
    # system + como máximo MAX_MENSAJES_CONTEXTO del historial + el mensaje actual
    assert len(llm.llamadas[0]) <= main.MAX_MENSAJES_CONTEXTO + 2
    assert "respuesta 49" in _contenidos(llm.llamadas[0], "assistant")


# ---------- Punto 3: mensajes atrasados ----------

def _post_firmado(cliente, payload):
    cuerpo = json.dumps(payload).encode()
    firma = "sha256=" + hmac.new(b"secreto_de_prueba", cuerpo, hashlib.sha256).hexdigest()
    return cliente.post("/meta-webhook", content=cuerpo, headers={"X-Hub-Signature-256": firma})


def _payload_texto(chat_id, wamid, texto, segundos_atras):
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "Cliente"}, "wa_id": chat_id}],
            "messages": [{
                "from": chat_id, "id": wamid, "type": "text",
                "timestamp": str(int(time.time() - segundos_atras)),
                "text": {"body": texto},
            }],
        }}]}]
    }


@pytest.fixture
def webhook(monkeypatch):
    encolados = []

    def debounce_falso(chat_id, nombre):
        encolados.append(chat_id)
        return asyncio.sleep(0)

    monkeypatch.setattr(main, "debounce_mensajes", debounce_falso)
    return TestClient(main.app), encolados


def test_mensaje_atrasado_se_responde(webhook):
    cliente, encolados = webhook
    r = _post_firmado(cliente, _payload_texto("51900000101", "wamid.atrasado1", "hola", 45 * 60))
    assert r.json() == {"status": "received_ok"}
    assert encolados == ["51900000101"]
    assert any(m["texto"] == "hola" for m in main.obtener_mensajes_chat("51900000101"))


def test_mensaje_atrasado_repetido_no_se_responde_dos_veces(webhook):
    cliente, encolados = webhook
    payload = _payload_texto("51900000102", "wamid.atrasado2", "hola", 45 * 60)
    _post_firmado(cliente, payload)
    r = _post_firmado(cliente, payload)
    assert r.json() == {"status": "duplicate_ignored"}
    assert encolados == ["51900000102"]
