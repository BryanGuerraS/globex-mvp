"""API de evaluación: corre preguntas de un banco con nuestra key de Cerebras (LLM simulado)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call

KEY = {"X-API-Key": "clave_eval_prueba"}


@pytest.fixture
def api(monkeypatch, bloquear_meta):
    monkeypatch.setattr(main, "EVAL_API_KEY", "clave_eval_prueba")
    main._llamadas_eval.clear()
    main._casos_eval_dia.clear()

    def con_llm(respuestas):
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "_cliente_cerebras_eval",
                            lambda: SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        return llm

    return TestClient(main.app), con_llm


def test_sin_key_o_sin_configurar_falla_cerrado(api, monkeypatch):
    cliente, _ = api
    caso = {"corrida_id": "C1", "id": "G006", "pregunta": "¿Qué pongo en State y ZIP?"}
    assert cliente.post("/api/eval/caso", json=caso).status_code == 401
    monkeypatch.setattr(main, "EVAL_API_KEY", None)
    assert cliente.post("/api/eval/caso", json=caso, headers=KEY).status_code == 503


def test_caso_faq_devuelve_respuesta_y_registros(api):
    cliente, con_llm = api
    llm = con_llm([
        _respuesta(tool_calls=[_tool_call("b1", "buscar_faq", {"preguntas": ["qué pongo en State y ZIP"]})]),
        _respuesta(tool_calls=[_tool_call("r1", "enviar_faq", {"ids": ["G006"]})]),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY,
                     json={"corrida_id": "C1", "id": "G006", "pregunta": "¿Qué pongo en State y ZIP?",
                           "banco_id": "FAQ_132"}).json()
    assert "33122" in r["respuesta_bot"] and r["error_ejecucion"] is None
    assert r["tipo_respuesta"] == "faq" and r["control_versiones"]["proveedor_chatbot"] == "Cerebras"
    acciones = r["registros_acciones"]
    assert [h["nombre"] for h in acciones["herramientas"]] == ["buscar_faq", "enviar_faq"]
    assert acciones["bot_pausado"] is False and r["registros_tiempo"]
    assert llm.llamadas  # usó el cliente de evaluación, no el de producción


def test_derivacion_queda_registrada_y_cada_caso_es_sesion_nueva(api):
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("d1", "derivar_a_asesor", {"motivo": "pide asesor"})])])
    r = cliente.post("/api/eval/caso", headers=KEY,
                     json={"corrida_id": "C2", "id": "G015", "pregunta": "Necesito atención de un asesor"}).json()
    acciones = r["registros_acciones"]
    assert acciones["bot_pausado"] and acciones["motivo_derivacion"] == "asesor"
    assert acciones["resumen_en_consola"]["publicado"]
    # el mismo id otra vez no hereda la sesión pausada
    con_llm([_respuesta(tool_calls=[_tool_call("d2", "derivar_a_asesor", {"motivo": "pide asesor"})])])
    r2 = cliente.post("/api/eval/caso", headers=KEY,
                      json={"corrida_id": "C2", "id": "G015", "pregunta": "Necesito atención de un asesor"}).json()
    assert r2["respuesta_bot"]
    resumen = cliente.get("/api/eval/resumen", params={"corrida_id": "C2"}, headers=KEY).json()
    assert resumen["casos"] == 2 and resumen["derivados"] == 2


def test_cotizacion_devuelve_el_total(api):
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "libro", "precio_unitario_usd": 40, "peso_kg": 1, "tax_tienda_usd": 0}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "C3", "id": "U01-01",
        "pregunta": "Un libro de USD 40,00, el checkout confirma TAX de USD 0,00, pesa 1,00 kg"}).json()
    assert r["cotizacion"]["emitida"] and r["cotizacion"]["total_proforma"] == 58.0


def test_tope_por_dia(api, monkeypatch):
    cliente, con_llm = api
    monkeypatch.setattr(main, "EVAL_MAX_CASOS_DIA", 1)
    con_llm([_respuesta(content="Hola 😊")])
    caso = {"corrida_id": "C4", "id": "X1", "pregunta": "hola"}
    assert cliente.post("/api/eval/caso", json=caso, headers=KEY).status_code == 200
    assert cliente.post("/api/eval/caso", json=caso, headers=KEY).status_code == 429


def test_varios_turnos_recopila_datos_y_devuelve_resumen(api):
    cliente, con_llm = api
    con_llm([
        _respuesta(content="¿Cuánto pesa aproximadamente en kg? 📦"),
        _respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
            {"producto": "Laptop Lenovo", "tienda": "Amazon", "precio_unitario_usd": 650, "peso_kg": 2.5}]})]),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "C5", "id": "REC-01",
        "mensajes": ["Quiero traer una laptop Lenovo de Amazon de 650 dólares", "Pesa 2.5 kg"]}).json()
    assert [t["tipo_respuesta"] for t in r["turnos"]] == ["pide_dato", "cotizacion"]
    datos = r["datos_recopilados"]
    assert datos["cotizacion_aceptada"] and datos["productos"][0]["precio"] == 650.0
    assert datos["productos"][0]["peso"] == 2.5 and datos["productos"][0]["tienda"] == "Amazon"
    resumen = r["resumen_caso"]
    assert resumen["publicado"] is False and resumen["campos_faltantes"] == []
    assert "Laptop Lenovo (Amazon) USD 650.00, 2.5 kg" in resumen["texto"]
    assert r["cotizacion"]["emitida"] and r["cotizacion"]["total_proforma"] > 650


def test_sin_pregunta_ni_mensajes_es_422(api):
    cliente, _ = api
    assert cliente.post("/api/eval/caso", headers=KEY,
                        json={"corrida_id": "C6", "id": "X"}).status_code == 422
    assert cliente.post("/api/eval/caso", headers=KEY,
                        json={"corrida_id": "C6", "id": "X", "mensajes": ["a"] * 7}).status_code == 422


def test_tras_derivar_los_turnos_siguientes_no_responden(api):
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("d1", "derivar_a_asesor", {"motivo": "pide asesor"})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "C7", "id": "DER", "mensajes": ["Quiero un asesor", "¿Sigues ahí?"]}).json()
    assert r["turnos"][1]["tipo_respuesta"] == "bot_pausado" and r["resumen_caso"]["publicado"]
