"""Pruebas de la experiencia de usuario: Globix, botones, listas, derivación y recuperación."""

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call


def _interactivos(payloads):
    return [p for p in payloads if p.get("type") == "interactive"]


def _textos(payloads):
    return [p["text"]["body"] for p in payloads if p.get("type") == "text"]


def _ids_botones(payload):
    return [b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]]


@pytest.fixture
def turno(monkeypatch, bloquear_meta):
    def correr(chat_id, texto, respuestas, nombre="Cliente"):
        main.registrar_mensaje_entrante(chat_id, nombre, texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        antes = len(bloquear_meta)
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, nombre, texto))
        return llm, bloquear_meta[antes:]

    return correr


# ---------- Nombre y textos ----------

@pytest.mark.parametrize(
    "perfil, esperado",
    [
        ("Ana Pérez", "Ana"),
        ("josé", "José"),
        ("ÑUÑO", "Ñuño"),
        ("🔥Rocky🔥", None),
        ("J.", None),
        ("", None),
        ("Cliente", None),
        ("Mamá de Luis", "Mamá"),
    ],
)
def test_nombre_de_pila(perfil, esperado):
    assert main.nombre_de_pila(perfil) == esperado


def test_bienvenida_primer_contacto():
    texto = main.texto_bienvenida("Ana", primer_contacto=True)
    assert texto.startswith("¡Hola! 👋")  # sin nombre: aún no lo sabemos
    assert "*Globix*, el asistente virtual de Globex Courier" in texto
    assert "Ana" not in texto
    assert "hablar con una persona" in texto


def test_bienvenida_sin_nombre_y_repetida():
    assert main.texto_bienvenida(None, True).startswith("¡Hola! 👋")
    assert main.texto_bienvenida("Ana", False) == "¿Hay algo más en lo que pueda ayudarte? 😊"


def test_derivacion_con_y_sin_nombre():
    assert main.texto_derivacion("Ana").startswith("¡Listo, Ana!")
    assert main.texto_derivacion(None).startswith("¡Listo! Un asesor")


def test_limites_de_meta():
    for botones in (main.BOTONES_MENU, main.BOTONES_POST_COTIZACION, main.BOTONES_RECUPERACION):
        assert 1 <= len(botones) <= 3
        assert all(len(t) <= 20 for _, t in botones)
    assert len(main.FILAS_OTRAS_CONSULTAS) <= 10
    assert all(len(t) <= 24 for _, t in main.FILAS_OTRAS_CONSULTAS)


def test_toda_opcion_tiene_texto():
    ids = {i for i, _ in main.BOTONES_MENU + main.BOTONES_POST_COTIZACION + main.BOTONES_RECUPERACION + main.FILAS_OTRAS_CONSULTAS}
    ids -= {"otras"}  # abre la lista, no va al LLM
    assert ids <= set(main.TEXTO_POR_OPCION)


@pytest.mark.parametrize("opcion", ["faq_direccion", "faq_plazos", "faq_provincias", "faq_como_funciona", "faq_pagos", "como_compro"])
def test_opciones_faq_encuentran_ficha(opcion):
    assert main.buscar_faq_comercial(main.TEXTO_POR_OPCION[opcion]) is not None


# ---------- Flujo con el LLM ----------

def test_saludo_muestra_bienvenida_con_botones(turno):
    llm, enviados = turno(
        "ux_hola", "hola", [_respuesta(tool_calls=[_tool_call("t1", "mostrar_menu", {})])], nombre="Ana Pérez"
    )
    (menu,) = _interactivos(enviados)
    assert menu["interactive"]["body"]["text"].startswith("¡Hola! 👋")
    assert _ids_botones(menu) == ["cotizar", "rastrear", "otras"]
    # El LLM sabe el nombre del cliente
    assert "El cliente se llama Ana." in llm.llamadas[0][0]["content"]


def test_segundo_menu_no_repite_presentacion(turno):
    turno("ux_menu2", "hola", [_respuesta(tool_calls=[_tool_call("t1", "mostrar_menu", {})])])
    _, enviados = turno("ux_menu2", "mmm", [_respuesta(tool_calls=[_tool_call("t2", "mostrar_menu", {})])])
    (menu,) = _interactivos(enviados)
    assert menu["interactive"]["body"]["text"] == "¿Hay algo más en lo que pueda ayudarte? 😊"


def test_cotizacion_confirma_datos_y_ofrece_botones(turno):
    _, enviados = turno(
        "ux_cot",
        "laptop Lenovo de 650 dólares, pesa 2.5 kg",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 650, "peso_kg": 2.5, "producto": "laptop Lenovo"})])],
    )
    # 1) Se sube la proforma como PNG, 2) se envía como imagen con la confirmación, 3) botones
    subida = [p for p in enviados if "subida_media" in p]
    assert subida and subida[0]["mime"] == "image/png" and subida[0]["bytes"] > 10_000
    (imagen,) = [p for p in enviados if p.get("type") == "image"]
    assert imagen["image"]["id"] == "media-de-prueba"
    assert imagen["image"]["caption"] == "Te envío adjunto tu cotización *referencial*."
    (msg,) = _interactivos(enviados)
    assert msg["interactive"]["body"]["text"].startswith("Total estimado: *USD 836.33*")
    assert _ids_botones(msg) == ["asesor", "cotizar_otro", "como_compro"]
    # No se manda el desglose en texto (va en la imagen)
    assert _textos(enviados) == []
    # En la BD queda el desglose (dashboard, historial del LLM) y el chat con su cotización
    textos = [m["texto"] for m in main.obtener_mensajes_chat("ux_cot") if m["emisor"] == "bot"]
    assert "[Proforma enviada como imagen" in textos[-2] and "Entendí: *laptop Lenovo" in textos[-2] and "COTIZACIÓN ESTIMADA" in textos[-2]
    assert "[Opciones: Hablar con asesor | Cotizar otro | ¿Cómo compro?]" in textos[-1]
    assert main.obtener_chat("ux_cot")["cotizacion_total"] == pytest.approx(836.33)


def test_si_falla_la_imagen_se_envia_en_texto(turno, monkeypatch):
    async def subida_fallida(*args):
        return None

    monkeypatch.setattr(main, "_subir_media_meta", subida_fallida)
    _, enviados = turno(
        "ux_cot_texto",
        "laptop de 650 dólares, pesa 2.5 kg",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 650, "peso_kg": 2.5})])],
    )
    assert [p for p in enviados if p.get("type") == "image"] == []
    (msg,) = _interactivos(enviados)
    assert "COTIZACIÓN ESTIMADA" in msg["interactive"]["body"]["text"]


def test_proforma_png_valida():
    import io
    from PIL import Image
    from pricing_engine import GlobexPricingEngine
    from proforma_imagen import codigo_proforma, generar_imagen_proforma

    png = generar_imagen_proforma(GlobexPricingEngine.calcular(45, 0.4), "Zapatillas", "Rashan Pérez", "PE.2347274009375408")
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width == 1080 and img.height > 1200
    assert codigo_proforma("PE.2347274009375408").endswith("-5408")


def test_derivacion_por_llm_sin_botones_y_con_nombre(turno):
    _, enviados = turno(
        "ux_der",
        "quiero hablar con alguien",
        [_respuesta(tool_calls=[_tool_call("t1", "derivar_a_asesor", {"motivo": "pide humano"})])],
        nombre="Ana Pérez",
    )
    assert _interactivos(enviados) == []
    assert _textos(enviados) == [main.texto_derivacion(None).removesuffix(" 🙌") + "\n\n" + main.PREGUNTA_NOMBRE]


def test_dos_fallos_seguidos_ofrecen_opciones(turno):
    _, primero = turno("ux_fallo", "asdf", [RuntimeError("Groq caído")])
    assert _textos(primero) == [main.RESPUESTA_ERROR]
    _, segundo = turno("ux_fallo", "qwer", [RuntimeError("Groq caído")])
    (menu,) = _interactivos(segundo)
    assert menu["interactive"]["body"]["text"] == main.TEXTO_RECUPERACION
    assert _ids_botones(menu) == ["cotizar", "rastrear", "asesor"]


def test_respuesta_larga_va_aparte_de_los_botones(turno, monkeypatch):
    monkeypatch.setattr(main, "LIMITE_CUERPO_INTERACTIVO", 50)
    _, enviados = turno("ux_largo", "hola", [_respuesta(tool_calls=[_tool_call("t1", "mostrar_menu", {})])])
    assert len(_textos(enviados)) == 1
    (menu,) = _interactivos(enviados)
    assert menu["interactive"]["body"]["text"] == "¿Qué deseas hacer ahora?"


# ---------- Webhook: toques de botones y "escribiendo…" ----------

def _post_firmado(cliente, payload):
    cuerpo = json.dumps(payload).encode()
    firma = "sha256=" + hmac.new(b"secreto_de_prueba", cuerpo, hashlib.sha256).hexdigest()
    return cliente.post("/meta-webhook", content=cuerpo, headers={"X-Hub-Signature-256": firma})


def _payload(chat_id, wamid, mensaje):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "Ana Pérez"}, "wa_id": chat_id}],
        "messages": [{"from": chat_id, "id": wamid, "timestamp": str(int(time.time())), **mensaje}],
    }}]}]}


def _boton(id_, titulo):
    return {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": id_, "title": titulo}}}


@pytest.fixture
def webhook(monkeypatch, bloquear_meta):
    encolados = []

    def debounce_falso(chat_id, nombre):
        encolados.append(chat_id)
        return asyncio.sleep(0)

    monkeypatch.setattr(main, "debounce_mensajes", debounce_falso)
    return TestClient(main.app), encolados, bloquear_meta


def test_boton_cotizar_entra_como_texto(webhook):
    cliente, encolados, enviados = webhook
    _post_firmado(cliente, _payload("51900000201", "wamid.b1", _boton("cotizar", "Cotizar envío")))
    assert main.obtener_mensajes_chat("51900000201")[-1]["texto"] == "Quiero cotizar un envío"
    assert encolados == ["51900000201"]
    assert main.message_buffer["51900000201"] == ["Quiero cotizar un envío"]


def test_texto_marca_leido_y_escribiendo(webhook):
    cliente, _, enviados = webhook
    _post_firmado(cliente, _payload("51900000202", "wamid.t1", {"type": "text", "text": {"body": "hola"}}))
    leido = [p for p in enviados if p.get("status") == "read"]
    assert leido == [{
        "messaging_product": "whatsapp", "status": "read",
        "message_id": "wamid.t1", "typing_indicator": {"type": "text"},
    }]


def test_otras_consultas_envia_lista_sin_llm(webhook):
    cliente, encolados, enviados = webhook
    r = _post_firmado(cliente, _payload("51900000203", "wamid.b2", _boton("otras", "Otras consultas")))
    assert r.json() == {"status": "list_sent"}
    assert encolados == []
    (lista,) = _interactivos(enviados)
    assert lista["interactive"]["type"] == "list"
    filas = lista["interactive"]["action"]["sections"][0]["rows"]
    assert [f["id"] for f in filas] == [i for i, _ in main.FILAS_OTRAS_CONSULTAS]


def test_fila_de_lista_entra_como_texto(webhook):
    cliente, encolados, _ = webhook
    msg = {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "faq_plazos", "title": "Plazos de entrega"}}}
    _post_firmado(cliente, _payload("51900000204", "wamid.l1", msg))
    assert main.obtener_mensajes_chat("51900000204")[-1]["texto"] == "¿Cuánto demora el envío?"
    assert encolados == ["51900000204"]


def test_boton_asesor_deriva_al_instante(webhook):
    cliente, encolados, enviados = webhook
    r = _post_firmado(cliente, _payload("51900000205", "wamid.b3", _boton("asesor", "Hablar con asesor")))
    assert r.json() == {"status": "derived_to_advisor"}
    assert encolados == []
    assert _textos(enviados) == [main.texto_derivacion(None).removesuffix(" 🙌") + "\n\n" + main.PREGUNTA_NOMBRE]
    assert main.esta_bot_activo("51900000205") is False


def test_chat_silenciado_no_muestra_escribiendo(webhook):
    cliente, encolados, enviados = webhook
    main.registrar_mensaje_entrante("51900000206", "Ana", "hola")
    main.actualizar_estado_chat("51900000206", "Listo para Asesor", bot_activo=0)
    _post_firmado(cliente, _payload("51900000206", "wamid.s1", {"type": "text", "text": {"body": "sigo aquí"}}))
    assert enviados == [] and encolados == []
