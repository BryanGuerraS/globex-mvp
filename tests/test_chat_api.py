"""/api/chat: una IA externa conversa con Globix con su propia key de Groq, sin WhatsApp."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)  # sin "with": no corre el startup (no llama a Meta)
HEADERS = {"X-API-Key": "chat_de_prueba", "X-Groq-Key": "gsk_del_amigo"}


def _respuesta(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _tool_call(id_, nombre, args):
    return SimpleNamespace(id=id_, type="function",
                           function=SimpleNamespace(name=nombre, arguments=json.dumps(args)))


@pytest.fixture
def llm_del_amigo(monkeypatch):
    """La key que llega en X-Groq-Key crea el cliente; el nuestro no debe usarse."""
    monkeypatch.setattr(main, "CHAT_API_KEY", "chat_de_prueba")
    monkeypatch.setattr(main, "_llamadas_chat_api", main.deque())
    keys, respuestas = [], []

    class LLM:
        def create(self, **kwargs):
            return respuestas.pop(0)

    def crear_cliente(key, respaldos):
        keys.append((key, respaldos))
        return SimpleNamespace(chat=SimpleNamespace(completions=LLM()))

    class Prohibido:
        def create(self, **kwargs):
            raise AssertionError("se usó nuestra key de Groq")

    monkeypatch.setattr(main, "crear_cliente", crear_cliente)
    monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=Prohibido())))
    return keys, respuestas


def test_cotiza_con_la_key_del_amigo_y_nada_sale_a_meta(llm_del_amigo, bloquear_meta):
    keys, respuestas = llm_del_amigo
    respuestas.append(_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion",
                                                        {"valor_producto_usd": 650, "peso_kg": 2.5})]))
    r = client.post("/api/chat", headers=HEADERS,
                    json={"sesion_id": "amigo-1", "mensaje": "Laptop de 650 dólares, 2.5 kg"})
    assert r.status_code == 200, r.text
    datos = r.json()
    assert keys == [("gsk_del_amigo", [])]  # su key, sin nuestras keys de respaldo
    assert datos["tipo_respuesta"] == "cotizacion" and datos["bot_activo"]
    assert datos["respuestas"][0]["tipo"] == "cotizacion" and "USD 893.92" in datos["respuestas"][0]["texto"]
    assert datos["respuestas"][1]["opciones"] == ["Hablar con asesor", "Cotizar otro", "¿Cómo compro?"]
    assert bloquear_meta == []  # ni mensajes ni imágenes a Meta
    assert main._cliente_externo.get() is None  # el cliente del amigo no queda para otros turnos


def test_rechaza_sin_claves_o_con_datos_invalidos(llm_del_amigo):
    ok = {"sesion_id": "amigo-2", "mensaje": "hola"}
    assert client.post("/api/chat", json=ok).status_code == 401
    assert client.post("/api/chat", headers={"X-API-Key": "chat_de_prueba"}, json=ok).status_code == 401
    assert client.post("/api/chat", headers={**HEADERS, "X-API-Key": "key_de_prueba"}, json=ok).status_code == 401
    assert client.post("/api/chat", headers=HEADERS, json={**ok, "sesion_id": "con espacio"}).status_code == 422
    assert client.post("/api/chat", headers=HEADERS, json={**ok, "mensaje": "x" * 1001}).status_code == 422


def test_falla_cerrado_sin_chat_api_key(monkeypatch):
    monkeypatch.setattr(main, "CHAT_API_KEY", None)
    assert client.post("/api/chat", headers=HEADERS, json={"sesion_id": "a", "mensaje": "hola"}).status_code == 503


def test_limite_por_minuto(llm_del_amigo, monkeypatch):
    monkeypatch.setattr(main, "CHAT_API_LIMITE_POR_MINUTO", 1)
    keys, respuestas = llm_del_amigo
    respuestas.append(_respuesta(content="¡Hola! ¿En qué te ayudo? 😊"))
    assert client.post("/api/chat", headers=HEADERS, json={"sesion_id": "a3", "mensaje": "hola"}).status_code == 200
    assert client.post("/api/chat", headers=HEADERS, json={"sesion_id": "a3", "mensaje": "hola"}).status_code == 429


def test_boton_por_su_titulo_y_chats_de_prueba_fuera_del_dashboard(llm_del_amigo):
    keys, respuestas = llm_del_amigo
    respuestas.append(_respuesta(content="Cuéntame qué producto quieres traer 😊"))
    r = client.post("/api/chat", headers=HEADERS, json={"sesion_id": "amigo-4", "mensaje": "Cotizar envío"})
    assert r.status_code == 200
    from database import obtener_mensajes_chat
    textos = [str(v) for m in obtener_mensajes_chat("PRUEBA-amigo-4") for v in m.values()]
    assert main.TEXTO_POR_OPCION["cotizar"] in textos  # el título del botón entró como en WhatsApp
    dash = {"X-API-Key": "key_de_prueba"}
    ids = [c["chat_id"] for c in client.get("/api/chats", headers=dash).json()]
    assert "PRUEBA-amigo-4" not in ids
    con_pruebas = client.get("/api/chats", headers=dash, params={"incluir_pruebas": True}).json()
    assert "PRUEBA-amigo-4" in [c["chat_id"] for c in con_pruebas]
    assert all(f["chat_id"] != "PRUEBA-amigo-4"
               for f in client.get("/api/metricas", headers=dash, params={"horas": 0}).json()["ultimos"])
