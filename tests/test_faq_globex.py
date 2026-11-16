"""Base de conocimiento ampliada (132 respuestas aprobadas): lectura, búsqueda y respuesta."""
import pytest

import json

import faq_globex
import main
from tests.test_tool_calling import _respuesta, _tool_call, entorno  # noqa: F401


def test_lee_las_132_entradas_con_todos_sus_campos():
    e = {k: v for k, v in faq_globex.entradas().items() if k.startswith("G")}
    assert len(e) == 132
    for x in e.values():
        assert x.get("pregunta") and all(x.get(c) for c in faq_globex.CAMPOS.values())


def test_busqueda_tolera_faltas_de_ortografia():
    assert faq_globex.buscar("k direcsion pongo pa k llegue al almacen", 1)[0]["tema"] == "Dirección del almacén"
    assert not any(c["id"] in faq_globex.EXCLUIDAS for c in faq_globex.buscar("que es el free tax de amazon", 5))


def _texto(enviado):
    if isinstance(enviado, str):
        return enviado
    if enviado.get("type") == "interactive":
        return enviado["interactive"]["body"]["text"]
    return enviado["text"]["body"]


def test_responde_dos_preguntas_con_las_respuestas_aprobadas(entorno):  # noqa: F811
    llm, enviado = entorno("PE.faq1", "¿Qué pongo en State y ZIP? ¿Y cuál es el teléfono del almacén?", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {
            "preguntas": ["qué pongo en State y ZIP", "cuál es el teléfono del almacén"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G006", "G007"]})]),
    ])
    busqueda = json.loads(llm.llamadas[1][-1]["content"])
    assert len(busqueda["busquedas"]) == 2
    texto = _texto(enviado)
    e = faq_globex.entradas()
    assert e["G006"]["respuesta"] in texto and e["G007"]["respuesta"] in texto
    assert main.obtener_chat("PE.faq1")["bot_activo"] == 1


def test_rechaza_un_id_que_no_salio_en_la_busqueda(entorno):  # noqa: F811
    llm, _ = entorno("PE.faq2", "¿qué es el tracking?", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["qué es el tracking"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G001"]})]),
        _respuesta(content="Disculpa, déjame revisarlo. 📦"),
    ])
    assert "error" in llm.llamadas[2][-1]["content"]


def test_deriva_cuando_la_orientacion_al_asesor_aplica(entorno):  # noqa: F811
    _, enviado = entorno("PE.faq3", "Quiero que ustedes me compren un producto con su tarjeta", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["compra con tarjeta de ustedes"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G058"], "derivar": True})]),
    ])
    chat = main.obtener_chat("PE.faq3")
    assert chat["bot_activo"] == 0 and chat["motivo_derivacion"] == "consulta"
    assert "Compra asistida" in chat["resumen_caso"]
    assert faq_globex.entradas()["G058"]["respuesta"] in _texto(enviado)


def test_acepta_las_faq_del_menu_como_candidatas(entorno):  # noqa: F811
    _, enviado = entorno("PE.faq4", "¿Envían por Olva a Arequipa?", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["¿Envían por Olva a Arequipa?"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["kb-cobertura_provincias"]})]),
    ])
    assert "solo por agencia Shalom" in _texto(enviado)


def test_reempaque_siempre_deriva_aunque_el_llm_no_lo_pida(entorno):  # noqa: F811
    _, enviado = entorno("PE.faq5", "¿Hacen reempaque?", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["¿Hacen reempaque?"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G126"], "derivar": False})]),
    ])
    chat = main.obtener_chat("PE.faq5")
    assert chat["bot_activo"] == 0 and chat["motivo_derivacion"] == "consulta"
    assert faq_globex.entradas()["G126"]["respuesta"] in _texto(enviado)


@pytest.mark.parametrize("faq_id, pregunta", [
    ("G037", "Mi paquete llegó dañado, ¿qué hago?"),
    ("G058", "La tienda solo acepta tarjetas de EE. UU., ¿pueden comprar por mí?"),
])
def test_reclamos_y_compra_asistida_siempre_derivan(entorno, faq_id, pregunta):  # noqa: F811
    chat_id = f"PE.{faq_id}"
    _, enviado = entorno(chat_id, pregunta, [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": [pregunta]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": [faq_id], "derivar": False})]),
    ])
    chat = main.obtener_chat(chat_id)
    assert chat["bot_activo"] == 0 and chat["motivo_derivacion"] == "consulta"


def test_enviar_faq_escrita_como_texto_se_ejecuta(entorno):  # noqa: F811
    """El modelo a veces escribe '{"ids":[...]}' en el texto en vez de llamar a enviar_faq."""
    _, enviado = entorno("PE.faqtexto", "¿Cuánto demora el envío?", [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["¿Cuánto demora el envío?"]})]),
        _respuesta(content='{"ids":["KB-plazos_entrega"],"derivar":false}⏱️ Plazos...'),
    ])
    texto = _texto(enviado)
    assert '"ids"' not in texto and "5 días hábiles" in texto


def test_pagos_no_derivan_aunque_el_llm_lo_pida(entorno):  # noqa: F811
    """Guía §6: explicar cómo pagar no es motivo de derivación."""
    pregunta = "¿Cómo pago el servicio? ¿Aceptan Yape?"
    _, enviado = entorno("PE.pago", pregunta, [
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["qué cuenta bancaria o Yape uso para pagar a Globex"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G116"], "derivar": True})]),
    ])
    chat = main.obtener_chat("PE.pago")
    assert chat["bot_activo"] == 1 and chat["motivo_derivacion"] is None
    assert "transferencia bancaria" in _texto(enviado)
