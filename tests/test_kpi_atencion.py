"""KPI de impacto: primera atención útil en <= 60 min (hallazgo 7)."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from database import get_connection
from metricas import kpi_primera_atencion
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call

API = {"X-API-Key": "key_de_prueba"}


@pytest.fixture
def turno(monkeypatch, bloquear_meta):
    def correr(chat_id, texto, respuestas):
        main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, "Cliente", texto))
        return main.obtener_chat(chat_id)

    return correr


# ---------- Registro en la BD ----------

def test_primer_mensaje_se_fija_una_sola_vez():
    main.registrar_mensaje_entrante("PE.k1", "Ana", "hola")
    primero = main.obtener_chat("PE.k1")["primer_mensaje_at"]
    main.registrar_mensaje_entrante("PE.k1", "Ana", "¿siguen ahí?")
    chat = main.obtener_chat("PE.k1")
    assert chat["primer_mensaje_at"] == primero
    assert chat["ultimo_mensaje_cliente_at"] >= primero


def test_menu_no_cuenta_y_cotizacion_si(turno):
    chat = turno("PE.k2", "hola", [_respuesta(tool_calls=[_tool_call("t1", "mostrar_menu", {})])])
    assert chat["primera_util_at"] is None  # un saludo no es atención útil
    chat = turno("PE.k2", "zapatillas de 120 dólares, 1.5 kg",
                 [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion",
                                                    {"valor_producto_usd": 120, "peso_kg": 1.5})])])
    assert chat["primera_util_at"] is not None
    assert (chat["primera_util_actor"], chat["primera_util_tipo"]) == ("bot", "cotizacion")


def test_faq_y_guardrail_cuentan(turno):
    chat = turno("PE.k3", "¿cuánto demora?",
                 [_respuesta(tool_calls=[_tool_call("t1", "consultar_faq_comercial", {"tema": "plazos"})]),
                  _respuesta(content="Demora de 5 a 7 días hábiles.")])
    assert chat["primera_util_tipo"] == "faq"
    chat = turno("PE.k4", "quiero traer 3 perfumes por $150", [])
    assert chat["primera_util_tipo"] == "guardrail"


@pytest.mark.parametrize("texto, respuestas", [
    ("2+2?", [_respuesta(tool_calls=[_tool_call("t1", "fuera_de_alcance", {"tema": "mate"})])]),
    ("asesor", [_respuesta(tool_calls=[_tool_call("t1", "derivar_a_asesor", {})])]),
    ("x", [RuntimeError("Groq caído")]),
])
def test_respuestas_que_no_cuentan(turno, texto, respuestas):
    chat_id = f"PE.k5_{abs(hash(texto))}"
    assert turno(chat_id, texto, respuestas)["primera_util_at"] is None


def test_solo_cuenta_la_primera(turno):
    turno("PE.k6", "laptop de 650 dólares, 2.5 kg",
          [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion",
                                             {"valor_producto_usd": 650, "peso_kg": 2.5})])])
    primera = main.obtener_chat("PE.k6")["primera_util_at"]
    assert main.marcar_atencion_util("PE.k6", "asesor", "mensaje_asesor") is False
    chat = main.obtener_chat("PE.k6")
    assert chat["primera_util_at"] == primera and chat["primera_util_actor"] == "bot"


def test_mensaje_del_asesor_cuenta(bloquear_meta):
    main.registrar_mensaje_entrante("PE.k7", "Ana", "hola")
    cliente = TestClient(main.app)
    r = cliente.post("/api/send-advisor-message", headers=API,
                     json={"chat_id": "PE.k7", "nombre_asesor": "Juan", "texto": "Hola, soy Juan"})
    assert r.status_code == 200
    chat = main.obtener_chat("PE.k7")
    assert (chat["primera_util_actor"], chat["primera_util_tipo"]) == ("asesor", "mensaje_asesor")


def test_endpoint_metricas_devuelve_kpi(bloquear_meta):
    main.registrar_mensaje_entrante("PE.k8", "Ana", "hola")
    with get_connection() as conn:  # lead de hace 2 h que nunca recibió atención útil
        conn.execute("UPDATE chats SET primer_mensaje_at = ? WHERE chat_id = 'PE.k8'",
                     (main.ahora() - timedelta(hours=2),))
        conn.commit()
    r = TestClient(main.app).get("/api/metricas", headers=API, params={"horas": 0})
    kpi = r.json()["kpi_atencion"]
    assert kpi["plazo_min"] == 60
    assert kpi["sin_atencion_util"] >= 1 and kpi["leads_evaluables"] >= 1


# ---------- Cálculo del KPI (función pura) ----------

T0 = datetime(2026, 11, 5, 10, 0)


def _lead(minutos_hasta_util=None, actor="bot", inicio=T0):
    util = inicio + timedelta(minutes=minutos_hasta_util) if minutos_hasta_util is not None else None
    return {"primer_mensaje_at": str(inicio), "primera_util_at": str(util) if util else None,
            "primera_util_actor": actor if util else None}


def test_kpi_cuenta_a_tiempo_tarde_y_sin_atencion():
    chats = [_lead(1), _lead(3), _lead(45, "asesor"), _lead(90, "asesor"), _lead(None),
             {"primer_mensaje_at": None}]  # chat sin primer mensaje: se ignora
    kpi = kpi_primera_atencion(chats, momento=T0 + timedelta(hours=3))
    assert kpi["leads_evaluables"] == 5
    assert kpi["a_tiempo"] == 3 and kpi["porcentaje"] == pytest.approx(0.6)
    assert kpi["sin_atencion_util"] == 1 and kpi["en_curso"] == 0
    assert kpi["por_actor"] == {"bot": {"atendidos": 2, "a_tiempo": 2},
                                "asesor": {"atendidos": 2, "a_tiempo": 1}}
    assert kpi["minutos_p50"] == pytest.approx(24)
    li, ls = kpi["ic95"]
    assert 0.14 < li < 0.15 and 0.94 < ls < 0.95  # Clopper-Pearson 3/5


def test_kpi_lead_dentro_del_plazo_queda_en_curso():
    kpi = kpi_primera_atencion([_lead(None)], momento=T0 + timedelta(minutes=30))
    assert kpi["en_curso"] == 1 and kpi["leads_evaluables"] == 0
    assert kpi["porcentaje"] is None and kpi["ic95"] is None


def test_kpi_filtra_por_periodo():
    viejo = _lead(5, inicio=T0 - timedelta(days=3))
    kpi = kpi_primera_atencion([viejo, _lead(5)], momento=T0 + timedelta(hours=2), desde=T0 - timedelta(days=1))
    assert kpi["leads_evaluables"] == 1


# ---------- Definición del E3: pedir un dato indispensable cuenta ----------

def test_pedir_dato_cuenta_como_atencion_util_pero_no_como_resolutiva(turno):
    chat = turno("PE.k9", "quiero traer una laptop de 650 dólares",
                 [_respuesta(content="¿Cuánto pesa aproximadamente en kg? 📦")])
    assert (chat["primera_util_actor"], chat["primera_util_tipo"]) == ("bot", "pide_dato")
    assert chat["primera_resolutiva_at"] is None  # la versión estricta espera a la cotización
    chat = turno("PE.k9", "2.5 kg", [_respuesta(tool_calls=[_tool_call(
        "t1", "calcular_cotizacion", {"valor_producto_usd": 650, "peso_kg": 2.5})])])
    assert chat["primera_util_tipo"] == "pide_dato"  # no cambia: solo cuenta la primera
    assert chat["primera_resolutiva_tipo"] == "cotizacion"


@pytest.mark.parametrize("respuesta", ["¡Hola! 👋 ¿En qué te ayudo?", "¿Me indicas tu nombre y apellido?",
                                       "¿Te ayudo con algo más? 😊"])
def test_saludo_o_pedir_nombre_no_cuentan(turno, respuesta):
    chat = turno(f"PE.k10_{abs(hash(respuesta))}", "hola", [_respuesta(content=respuesta)])
    assert chat["primera_util_at"] is None


def test_kpi_estricto_aparte(bloquear_meta):
    datos = TestClient(main.app).get("/api/metricas", headers=API, params={"horas": 0}).json()
    assert datos["kpi_atencion_resolutiva"]["plazo_min"] == 60
    lead = {"primer_mensaje_at": str(T0), "primera_util_at": str(T0 + timedelta(minutes=1)),
            "primera_resolutiva_at": str(T0 + timedelta(minutes=90))}
    momento = T0 + timedelta(hours=3)
    assert kpi_primera_atencion([lead], momento)["a_tiempo"] == 1
    assert kpi_primera_atencion([lead], momento, campo="primera_resolutiva")["a_tiempo"] == 0
