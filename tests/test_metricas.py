"""Pruebas de la medición de costo, latencia y herramientas por turno (punto 3)."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
import metricas
from tests.test_tool_calling import LLMFalso, _tool_call


def _respuesta(content=None, tool_calls=None, entrada=1000, salida=50):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    uso = SimpleNamespace(prompt_tokens=entrada, completion_tokens=salida)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=uso)


@pytest.fixture
def turno(monkeypatch, bloquear_meta):
    def correr(chat_id, texto, respuestas):
        main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, "Cliente", texto))
        filas = [f for f in main.obtener_metricas() if f["chat_id"] == chat_id]
        return filas[-1]

    return correr


# ---------- Cálculos ----------

def test_costo_usd_con_precios_de_groq():
    # 1M de entrada y 1M de salida = 0.15 + 0.60
    assert metricas.costo_usd(1_000_000, 1_000_000) == pytest.approx(0.75)
    assert metricas.costo_usd(2000, 100) == pytest.approx(0.00036)


def test_percentiles():
    valores = [100, 200, 300, 400, 500]
    assert metricas._percentil(valores, 50) == 300
    assert metricas._percentil(valores, 95) == pytest.approx(480)
    assert metricas._percentil([], 50) is None


def test_resumen():
    filas = [
        {"chat_id": "a", "tipo_respuesta": "cotizacion", "llamadas_llm": 1, "tokens_entrada": 1000,
         "tokens_salida": 100, "costo_usd": 0.001, "latencia_llm_ms": 800, "latencia_procesamiento_ms": 900,
         "latencia_total_ms": 6000},
        {"chat_id": "a", "tipo_respuesta": "libre", "llamadas_llm": 1, "tokens_entrada": 1200,
         "tokens_salida": 60, "costo_usd": 0.003, "latencia_llm_ms": 1200, "latencia_procesamiento_ms": 1300,
         "latencia_total_ms": 7000},
        {"chat_id": "b", "tipo_respuesta": "guardrail", "llamadas_llm": 0, "tokens_entrada": 0,
         "tokens_salida": 0, "costo_usd": 0.0, "latencia_llm_ms": 0, "latencia_procesamiento_ms": 20,
         "latencia_total_ms": 5100},
    ]
    r = metricas.resumir(filas)
    assert r["turnos"] == 3 and r["conversaciones"] == 2
    assert r["costo_total_usd"] == pytest.approx(0.004)
    assert r["costo_por_conversacion_usd"] == pytest.approx(0.002)
    assert r["costo_por_1000_conversaciones_usd"] == pytest.approx(2.0)
    # La latencia del LLM solo cuenta turnos que lo usaron
    assert r["latencia_llm"]["p50_ms"] == 1000
    assert r["tipos_respuesta"] == {"cotizacion": 1, "libre": 1, "guardrail": 1}
    assert metricas.resumir([]) == {"turnos": 0}


# ---------- Registro por turno ----------

def test_turno_de_cotizacion_registra_tokens_costo_y_herramienta(turno):
    fila = turno(
        "m_cot",
        "laptop de 650 dólares, 2.5 kg",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion",
                                           {"valor_producto_usd": 650, "peso_kg": 2.5, "producto": "laptop"})],
                    entrada=1500, salida=40)],
    )
    assert fila["tipo_respuesta"] == "cotizacion"
    assert fila["llamadas_llm"] == 1
    assert (fila["tokens_entrada"], fila["tokens_salida"]) == (1500, 40)
    assert fila["costo_usd"] == pytest.approx(metricas.costo_usd(1500, 40))
    assert fila["latencia_llm_ms"] >= 0 and fila["latencia_procesamiento_ms"] >= fila["latencia_llm_ms"]
    (herr,) = json.loads(fila["herramientas"])
    assert herr["nombre"] == "calcular_cotizacion"
    assert json.loads(herr["argumentos"])["valor_producto_usd"] == 650
    assert herr["resultado"] == {"cotizacion_emitida": True}


def test_varias_llamadas_al_llm_se_suman(turno):
    fila = turno(
        "m_dos",
        "un iphone de 900 dólares",
        [
            _respuesta(tool_calls=[_tool_call("t1", "consultar_peso_producto", {"nombre_producto": "iphone"})],
                       entrada=1000, salida=20),
            _respuesta(content="¿Es el iPhone 15?", entrada=1200, salida=10),
        ],
    )
    assert fila["llamadas_llm"] == 2
    assert (fila["tokens_entrada"], fila["tokens_salida"]) == (2200, 30)
    assert fila["tipo_respuesta"] == "libre"


@pytest.mark.parametrize(
    "texto, respuestas, tipo",
    [
        ("hola", [_respuesta(tool_calls=[_tool_call("t1", "mostrar_menu", {})])], "menu"),
        ("2+2?", [_respuesta(tool_calls=[_tool_call("t1", "fuera_de_alcance", {"tema": "mate"})])], "fuera_de_alcance"),
        ("python?", [_respuesta(content="Usa `sorted()`")], "bloqueado:codigo"),
        ("asesor", [_respuesta(tool_calls=[_tool_call("t1", "derivar_a_asesor", {})])], "derivacion"),
        ("x", [RuntimeError("Groq caído")], "error"),
    ],
)
def test_tipo_de_respuesta(turno, texto, respuestas, tipo):
    chat = f"m_tipo_{tipo.replace(':', '_')}"
    assert turno(chat, texto, respuestas)["tipo_respuesta"] == tipo


def test_guardrail_se_registra_sin_llm(turno):
    fila = turno("m_guard", "quiero traer unos vapes", [])
    assert fila["tipo_respuesta"] == "guardrail"
    assert fila["llamadas_llm"] == 0 and fila["costo_usd"] == 0


def test_latencia_total_incluye_la_espera_desde_el_primer_mensaje(turno):
    main.llegada_buffer["m_espera"] = time.monotonic() - 6.0  # llegó hace 6 s (debounce)
    fila = turno("m_espera", "hola", [_respuesta(content="¡Hola!")])
    assert fila["latencia_total_ms"] >= 6000
    assert "m_espera" not in main.llegada_buffer


# ---------- Endpoint ----------

def test_endpoint_metricas(turno):
    turno("m_api", "hola", [_respuesta(content="¡Hola!", entrada=800, salida=20)])
    cliente = TestClient(main.app)
    assert cliente.get("/api/metricas").status_code == 401
    r = cliente.get("/api/metricas", params={"horas": 0}, headers={"X-API-Key": "key_de_prueba"})
    assert r.status_code == 200
    datos = r.json()
    assert datos["resumen"]["turnos"] >= 1
    assert datos["resumen"]["precio_usd_por_millon"] == {"entrada": 0.15, "salida": 0.60}
    assert datos["ultimos"][-1]["chat_id"] == "m_api"
