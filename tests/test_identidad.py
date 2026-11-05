"""Pruebas del ID único del cliente (BSUID) y del nombre pedido al derivar."""

import asyncio
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import main
from validaciones import extraer_nombre


# ---------- Identificador del cliente ----------

def test_usa_bsuid_aunque_haya_telefono():
    msg = {"from": "51999888777", "id": "w"}
    contacts = [{"wa_id": "51999888777", "user_id": "PE.1111"}]
    assert main.identificar_cliente(msg, contacts) == ("PE.1111", "51999888777")


def test_usuario_con_numero_oculto():
    msg = {"from": "PE.2222", "id": "w"}
    contacts = [{"wa_id": "PE.2222", "user_id": "PE.2222", "username": "@ana"}]
    assert main.identificar_cliente(msg, contacts) == ("PE.2222", None)


def test_bsuid_en_from_user_id():
    assert main.identificar_cliente({"from_user_id": "PE.3333"}, []) == ("PE.3333", None)


def test_payload_antiguo_sin_bsuid_usa_telefono():
    msg = {"from": "51999000111"}
    assert main.identificar_cliente(msg, [{"wa_id": "51999000111"}]) == ("51999000111", "51999000111")


def test_sin_identificador():
    assert main.identificar_cliente({}, []) == (None, None)


# ---------- Extracción del nombre ----------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Ana", "Ana"),
        ("ana pérez", "Ana Pérez"),
        ("Me llamo José Luis", "José Luis"),
        ("mi nombre es María de la Cruz", "María De La Cruz"),
        ("Soy Rocío.", "Rocío"),
        ("Claro, soy Pedro Gómez", "Pedro Gómez"),
    ],
)
def test_extrae_nombre(texto, esperado):
    assert extraer_nombre(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    ["ok", "gracias", "Sí", "¿Cuánto demora?", "quiero cotizar un envío", "ya", "123", "", "hola",
     "esperando al asesor por favor ya"],
)
def test_no_confunde_con_nombre(texto):
    assert extraer_nombre(texto) is None


# ---------- Flujo: pedir y guardar el nombre al derivar ----------

def _post_firmado(cliente, payload):
    cuerpo = json.dumps(payload).encode()
    firma = "sha256=" + hmac.new(b"secreto_de_prueba", cuerpo, hashlib.sha256).hexdigest()
    return cliente.post("/meta-webhook", content=cuerpo, headers={"X-Hub-Signature-256": firma})


def _payload(bsuid, wamid, mensaje, telefono=None, perfil="🔥Rocky🔥"):
    contacto = {"profile": {"name": perfil}, "user_id": bsuid, "wa_id": telefono or bsuid}
    return {"entry": [{"changes": [{"value": {
        "contacts": [contacto],
        "messages": [{"from": telefono or bsuid, "id": wamid, "timestamp": str(int(time.time())), **mensaje}],
    }}]}]}


def _texto(t):
    return {"type": "text", "text": {"body": t}}


def _boton_asesor():
    return {"type": "interactive", "interactive": {
        "type": "button_reply", "button_reply": {"id": "asesor", "title": "Hablar con asesor"}}}


@pytest.fixture
def webhook(monkeypatch, bloquear_meta):
    encolados = []

    def debounce_falso(chat_id, nombre):
        encolados.append(chat_id)
        return asyncio.sleep(0)

    monkeypatch.setattr(main, "debounce_mensajes", debounce_falso)
    return TestClient(main.app), encolados, bloquear_meta


def _textos(payloads):
    return [p["text"]["body"] for p in payloads if p.get("type") == "text"]


def test_chat_se_guarda_con_bsuid_y_telefono_aparte(webhook):
    cliente, _, _ = webhook
    _post_firmado(cliente, _payload("PE.5001", "wamid.i1", _texto("hola"), telefono="51911111111"))
    chat = main.obtener_chat("PE.5001")
    assert chat["telefono"] == "51911111111"
    assert main.obtener_chat("51911111111") is None


def test_pide_nombre_al_derivar_y_lo_guarda(webhook):
    cliente, _, enviados = webhook
    _post_firmado(cliente, _payload("PE.5002", "wamid.n1", _boton_asesor()))
    assert _textos(enviados)[-1].endswith(main.PREGUNTA_NOMBRE)
    assert main.obtener_chat("PE.5002")["esperando_nombre"] == 1

    r = _post_firmado(cliente, _payload("PE.5002", "wamid.n2", _texto("Me llamo Ana Pérez")))
    assert r.json() == {"status": "name_saved"}
    chat = main.obtener_chat("PE.5002")
    assert chat["nombre_cliente"] == "Ana Pérez" and chat["esperando_nombre"] == 0
    assert _textos(enviados)[-1] == "¡Gracias, Ana! Ya se lo pasé a tu asesor. 🙌"
    assert chat["bot_activo"] == 0  # sigue con el asesor


def test_si_no_es_nombre_no_insiste(webhook):
    cliente, _, enviados = webhook
    _post_firmado(cliente, _payload("PE.5003", "wamid.x1", _boton_asesor()))
    antes = len(enviados)
    r = _post_firmado(cliente, _payload("PE.5003", "wamid.x2", _texto("¿cuánto demora?")))
    assert r.json() == {"status": "bot_silenced_for_human"}
    assert len(enviados) == antes  # no responde: lo ve el asesor
    chat = main.obtener_chat("PE.5003")
    assert chat["nombre_cliente"] is None and chat["esperando_nombre"] == 0
    # Una palabra suelta posterior ya no se toma como nombre
    _post_firmado(cliente, _payload("PE.5003", "wamid.x3", _texto("Ana")))
    assert main.obtener_chat("PE.5003")["nombre_cliente"] is None


def test_no_vuelve_a_pedir_nombre_si_ya_lo_tiene(webhook):
    cliente, _, enviados = webhook
    _post_firmado(cliente, _payload("PE.5004", "wamid.r1", _texto("hola")))
    main.guardar_nombre_cliente("PE.5004", "Luis Gómez")
    _post_firmado(cliente, _payload("PE.5004", "wamid.r2", _boton_asesor()))
    ultimo = _textos(enviados)[-1]
    assert ultimo.startswith("Listo, Luis.")
    assert main.PREGUNTA_NOMBRE not in ultimo


def test_nombre_dado_tiene_prioridad_sobre_perfil():
    main.registrar_mensaje_entrante("PE.5005", "Mamá de Luis", "hola")
    assert main.nombre_para_saludo("PE.5005", "Mamá de Luis") == "Mamá"
    main.guardar_nombre_cliente("PE.5005", "Carmen Ruiz")
    assert main.nombre_para_saludo("PE.5005", "Mamá de Luis") == "Carmen"


# ---------- Respaldo de envío por teléfono ----------

def test_si_meta_rechaza_el_id_reintenta_con_telefono(monkeypatch):
    main.registrar_mensaje_entrante("PE.5006", "Ana", "hola")
    main.guardar_telefono("PE.5006", "51922222222")
    intentos = []

    async def post(payload):
        intentos.append(payload)
        return "to" in payload  # Meta acepta solo por teléfono

    monkeypatch.setattr(main, "_post_meta", post)
    asyncio.run(main.send_meta_whatsapp_message("PE.5006", "hola"))
    assert [("recipient" in p, p.get("to")) for p in intentos] == [(True, None), (False, "51922222222")]


def test_sin_telefono_no_hay_reintento(monkeypatch):
    main.registrar_mensaje_entrante("PE.5007", "Ana", "hola")
    intentos = []

    async def post(payload):
        intentos.append(payload)
        return False

    monkeypatch.setattr(main, "_post_meta", post)
    asyncio.run(main.send_meta_whatsapp_message("PE.5007", "hola"))
    assert len(intentos) == 1
