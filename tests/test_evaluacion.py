"""Pruebas del script de evaluación (sin llamar a Groq)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import main
from evaluacion import evaluar as ev
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call


# ---------- Clopper-Pearson ----------

@pytest.mark.parametrize(
    "x, n, esperado",
    [
        (30, 30, (0.8843, 1.0)),      # 30/30: solo garantiza ≥ 88.4 %
        (0, 30, (0.0, 0.1157)),
        (15, 30, (0.3130, 0.6870)),
        (9, 10, (0.5550, 0.9975)),
    ],
)
def test_clopper_pearson(x, n, esperado):
    li, ls = ev.clopper_pearson(x, n)
    assert li == pytest.approx(esperado[0], abs=1e-3)
    assert ls == pytest.approx(esperado[1], abs=1e-3)


def test_clopper_pearson_sin_datos():
    assert ev.clopper_pearson(0, 0) == (0.0, 1.0)


# ---------- Verificaciones de una corrida ----------

def _corrida(turnos, bot_activo=1):
    return {"turnos": turnos, "bot_activo_final": bot_activo}


def _turno(tipo, herramientas=(), respuestas=("ok",)):
    return {"cliente": "x", "tipo_respuesta": tipo, "herramientas": list(herramientas), "respuestas": list(respuestas)}


def _cot(valor, peso):
    return {"nombre": "calcular_cotizacion",
            "argumentos": json.dumps({"valor_producto_usd": valor, "peso_kg": peso}),
            "resultado": {"cotizacion_emitida": True}}


def _ok(checks):
    return {c["check"]: c["ok"] for c in checks}


def test_cotizacion_correcta():
    caso = {"esperado": {"tipo_final": ["cotizacion"], "herramientas": ["calcular_cotizacion"],
                         "cotizacion": {"valor": 650, "peso": 2.5}, "cotiza": True, "deriva": False}}
    checks = ev.evaluar_corrida(caso, _corrida([_turno("cotizacion", [_cot(650, 2.5)])]))
    assert all(c["ok"] for c in checks)


def test_argumentos_equivocados_fallan():
    caso = {"esperado": {"cotizacion": {"valor": 650, "peso": 2.5}}}
    checks = ev.evaluar_corrida(caso, _corrida([_turno("cotizacion", [_cot(650, 3)])]))
    assert _ok(checks) == {"argumentos_cotizacion": False}


def test_cotizacion_indebida():
    caso = {"esperado": {"cotiza": False}}
    checks = ev.evaluar_corrida(caso, _corrida([_turno("cotizacion", [_cot(640, 2)])]))
    assert _ok(checks) == {"no_cotiza_indebidamente": False}


def test_tipo_bloqueado_y_compuesto():
    caso = {"esperado": {"tipo_final": ["fuera_de_alcance", "bloqueado"]}}
    assert ev.evaluar_corrida(caso, _corrida([_turno("bloqueado:codigo")]))[0]["ok"]
    caso = {"esperado": {"tipo_final": ["faq"]}}
    assert ev.evaluar_corrida(caso, _corrida([_turno("cotizacion+faq")]))[0]["ok"]


def test_derivacion_y_textos():
    caso = {"esperado": {"deriva": True, "contiene": ["asesor"], "no_contiene": ["sort"]}}
    checks = ev.evaluar_corrida(caso, _corrida([_turno("derivacion", respuestas=["Te paso con un asesor"])], bot_activo=0))
    assert all(c["ok"] for c in checks)
    checks = ev.evaluar_corrida(caso, _corrida([_turno("libre", respuestas=["usa sort()"])], bot_activo=1))
    assert _ok(checks) == {"deriva": False, "contiene:asesor": False, "no_contiene:sort": False}


# ---------- KPIs ----------

def test_kpis_y_pass_k():
    casos = [
        {"id": "A", "categoria": "cotizacion", "esperado": {"tipo_final": ["cotizacion"], "cotiza": True}},
        {"id": "B", "categoria": "alcance", "esperado": {"tipo_final": ["fuera_de_alcance"], "cotiza": False}},
    ]

    def r(exito, checks):
        return {"exito": exito, "checks": checks}

    resultados = {
        "A": [r(True, [{"check": "tipo_final", "ok": True}]), r(True, [{"check": "tipo_final", "ok": True}])],
        "B": [r(True, [{"check": "tipo_final", "ok": True}, {"check": "no_cotiza_indebidamente", "ok": True}]),
              r(False, [{"check": "tipo_final", "ok": False}, {"check": "no_cotiza_indebidamente", "ok": True}])],
    }
    k = ev.calcular_kpis(casos, resultados)
    assert k["exito_tarea_pass1"]["exitos"] == 3 and k["exito_tarea_pass1"]["n"] == 4
    assert k["consistencia_pass^2"]["exitos"] == 1 and k["consistencia_pass^2"]["n"] == 2
    assert k["K3_sin_cotizacion_indebida"]["valor"] == 1.0
    assert k["K11_adherencia_alcance"]["exitos"] == 1


# ---------- Corrida completa con LLM simulado ----------

def test_evaluar_de_punta_a_punta_con_llm_simulado(monkeypatch):
    casos = [
        {"id": "COT", "categoria": "cotizacion", "descripcion": "x", "mensajes": ["laptop de $650, 2.5 kg"],
         "esperado": {"tipo_final": ["cotizacion"], "cotizacion": {"valor": 650, "peso": 2.5}, "cotiza": True, "deriva": False}},
        {"id": "ASE", "categoria": "derivacion", "descripcion": "y", "mensajes": ["quiero un asesor", "sigo aquí"],
         "esperado": {"tipo_final": ["derivacion"], "deriva": True}},
    ]
    respuestas = [
        _respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 650, "peso_kg": 2.5})]),
        _respuesta(tool_calls=[_tool_call("t2", "derivar_a_asesor", {})]),
    ]
    monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=LLMFalso(respuestas))))
    resultados = asyncio.run(ev.evaluar(main, casos, repeticiones=1))
    assert resultados["COT"][0]["exito"], resultados["COT"][0]["checks"]
    assert resultados["ASE"][0]["exito"], resultados["ASE"][0]["checks"]
    # El segundo mensaje llega con el bot silenciado: queda para el asesor
    assert resultados["ASE"][0]["turnos"][1]["silenciado"] is True
    reporte = ev.generar_reporte(
        {"fecha": "hoy", "archivo_casos": "x.json", "repeticiones": 1, "modelo": "m", "duracion_s": 1},
        casos, resultados, ev.calcular_kpis(casos, resultados), main.resumir_metricas(main.obtener_metricas()),
    )
    assert "## KPIs" in reporte and "| COT | cotizacion | ✅ |" in reporte and "Sin fallas" in reporte


def test_reporte_pdf(tmp_path, monkeypatch):
    from evaluacion.reporte_pdf import generar_reporte_pdf

    casos = [{"id": "COT", "categoria": "cotizacion", "descripcion": "Cotización 👋", "mensajes": ["x"],
              "esperado": {"cotiza": True}}]
    corrida = {"chat_id": "EVAL-COT", "repeticion": 1, "exito": False, "bot_activo_final": 1,
               "checks": [{"check": "cotiza", "ok": False, "detalle": "cotizó=False"}],
               "turnos": [{"cliente": "laptop de $650 😀", "respuestas": ["¿Cuánto pesa? 📦"], "tipo_respuesta": "libre",
                           "herramientas": [{"nombre": "consultar_peso_producto", "argumentos": "{}", "resultado": {}}],
                           "llamadas_llm": 1, "tokens_entrada": 1500, "tokens_salida": 40, "latencia_llm_ms": 900}]}
    resultados = {"COT": [corrida]}
    meta = {"fecha": "hoy", "archivo_casos": "x.json", "repeticiones": 1, "modelo": "m", "duracion_s": 3}
    ruta = generar_reporte_pdf(meta, casos, resultados, ev.calcular_kpis(casos, resultados), {"turnos": 0},
                               str(tmp_path / "r.pdf"))
    contenido = open(ruta, "rb").read()
    assert contenido.startswith(b"%PDF") and len(contenido) > 5_000
