"""Metas mínimas de KPIs y resumen global en PDF."""

import pytest

from evaluacion.kpis_minimos import KPIS_MINIMOS, evaluar_estado
from evaluacion.resumen_kpis import construir_kpis, generar_resumen_pdf
from evaluacion.verificar_motor import verificar_todos

META_MIN = {"meta": 0.90, "sentido": "min"}
META_MAX = {"meta": 10.0, "sentido": "max"}


@pytest.mark.parametrize("meta, valor, ic, estado", [
    (META_MIN, 0.97, [0.91, 0.99], "Cumple"),
    (META_MIN, 0.93, [0.86, 0.97], "Cumple (falta n)"),
    (META_MIN, 0.85, [0.70, 0.94], "No cumple"),
    (META_MIN, None, None, "Sin datos"),
    (META_MIN, 0.95, None, "Cumple"),  # sin IC (determinista)
    (META_MAX, 7.8, None, "Cumple"),
    (META_MAX, 27.9, None, "No cumple"),
])
def test_estado(meta, valor, ic, estado):
    assert evaluar_estado(meta, valor, ic) == estado


def test_cada_meta_tiene_fuente_y_clave_unica():
    claves = [k["clave"] for k in KPIS_MINIMOS]
    assert len(claves) == len(set(claves))
    assert all(k["fuente"] and k["sentido"] in ("min", "max") for k in KPIS_MINIMOS)


EVAL = {
    "meta": {"fecha": "05/11/2026 00:40", "archivo_casos": "no_existe.json", "repeticiones": 3,
             "modelo": "openai/gpt-oss-120b"},
    "kpis": {"K1_exactitud_herramienta": {"exitos": 84, "n": 90, "valor": 84 / 90, "ic95": [0.86, 0.975]},
             "K5_guardrail": {"exitos": 0, "n": 0, "valor": None, "ic95": None}},
    "costo_latencia": {"latencia_total_cliente": {"p50_ms": 2800, "p95_ms": 22900},
                       "costo_por_1000_conversaciones_usd": 0.35},
    "resultados": {"COT-01": [{"repeticion": 1, "exito": True, "checks": []}],
                   "FAL-03": [{"repeticion": 1, "exito": False,
                               "checks": [{"check": "tipo_final", "ok": False, "detalle": "x"}]}]},
}


def test_construir_kpis_une_fuentes():
    kpis = {k["clave"]: k for k in construir_kpis(verificar_todos(), {"passed": 10, "failed": 0, "xfailed": 1}, EVAL)}
    assert kpis["V1_motor"]["detalle"] == "36/36"
    assert kpis["V2_pruebas"]["estado"] == "Cumple"
    assert kpis["K1_exactitud_herramienta"]["estado"] == "Cumple (falta n)"
    assert kpis["K5_guardrail"]["estado"] == "Sin datos"  # n = 0
    assert kpis["espera_p50_s"]["valor"] == pytest.approx(7.8)  # suma los 5 s del debounce
    assert kpis["espera_p95_s"]["estado"] == "No cumple"
    assert kpis["kpi_atencion_60"]["estado"] == "Sin datos"


def test_genera_pdf(tmp_path):
    motor = verificar_todos()
    kpis = construir_kpis(motor, None, EVAL)
    ruta = generar_resumen_pdf(kpis, motor, None, EVAL, "resultados_prueba.json", str(tmp_path / "r.pdf"))
    with open(ruta, "rb") as f:
        assert f.read(5) == b"%PDF-"


@pytest.mark.parametrize("meta, necesarias", [(0.95, 72), (0.90, 36), (0.85, 23), (0.80, 17)])
def test_corridas_necesarias(meta, necesarias):
    from evaluacion.kpis_minimos import corridas_necesarias
    from metricas import clopper_pearson
    k = {"meta": meta, "sentido": "min", "unidad": "%"}
    assert corridas_necesarias(k) == necesarias
    assert clopper_pearson(necesarias, necesarias)[0] >= meta  # con n alcanza
    assert clopper_pearson(necesarias - 1, necesarias - 1)[0] < meta  # con uno menos no


def test_meta_100_se_garantiza_al_95():
    k = {"meta": 1.0, "garantia": 0.95, "sentido": "min", "unidad": "%"}
    assert evaluar_estado(k, 1.0, [0.951, 1.0]) == "Cumple"
    assert evaluar_estado(k, 1.0, [0.94, 1.0]) == "Cumple (falta n)"
    assert evaluar_estado(k, 0.99, [0.94, 1.0]) == "No cumple"  # un fallo ya no cumple
