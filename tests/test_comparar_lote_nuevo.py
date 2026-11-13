"""Comparación v0 / v1 / reglas del lote nuevo (reglas del pre-registro)."""

import json

import pytest

from evaluacion import comparar_lote_nuevo as cl
from evaluacion import correr_lote_nuevo as corr


def _corrida(tmp_path, nombre, por_caso):
    """por_caso: id -> (exito, {check: ok})"""
    datos = {"resultados": {cid: [{"exito": ex, "checks": [{"check": k, "ok": v} for k, v in cs.items()]}]
                            for cid, (ex, cs) in por_caso.items()}}
    ruta = tmp_path / f"{nombre}.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return str(ruta)


CASOS = [
    {"id": "A", "esperado": {"cotizacion": {"valor": 10, "peso": 1}}, "banco": {"estado_referencia": "Listo"}},
    {"id": "B", "esperado": {"cotiza": False}, "banco": {"estado_referencia": "Listo"}},
    {"id": "C", "esperado": {"deriva": False}, "banco": {"estado_referencia": "Validación parcial"}},
]


def test_bootstrap_diferencia_es_determinista_y_contiene_la_diferencia():
    a = [{"x": True, "y": True, "z": False}]
    b = [{"x": False, "y": True, "z": False}]
    r1 = cl.bootstrap_diferencia(a, b, ["x", "y", "z"])
    r2 = cl.bootstrap_diferencia(a, b, ["x", "y", "z"])
    assert r1 == r2 and r1["n"] == 3
    assert r1["diferencia"] == pytest.approx(1 / 3)
    assert r1["ic95"][0] <= r1["diferencia"] <= r1["ic95"][1]


def test_tasa_media_entre_corridas():
    a = [{"x": True}, {"x": False}]  # 0.5
    b = [{"x": False}]
    assert cl.bootstrap_diferencia(a, b, ["x"])["diferencia"] == pytest.approx(0.5)


def test_comparar_checks_en_todos_k2_en_cotizacion_y_contrapeso(tmp_path):
    v1 = _corrida(tmp_path, "v1", {"A": (True, {"argumentos_cotizacion": True}),
                                   "B": (True, {"no_cotiza_indebidamente": True}),
                                   "C": (True, {"no_deriva": True})})
    v0 = _corrida(tmp_path, "v0", {"A": (False, {"argumentos_cotizacion": False}),
                                   "B": (False, {"no_cotiza_indebidamente": False}),
                                   "C": (True, {"no_deriva": True})})
    reglas = _corrida(tmp_path, "r", {"A": (True, {"argumentos_cotizacion": True}),
                                      "B": (True, {"no_cotiza_indebidamente": True}),
                                      "C": (False, {"no_deriva": False})})
    r = cl.comparar(CASOS, {"v0": [v0], "v1": [v1], "reglas": [reglas]}, {})
    assert r["metricas"]["checks"]["n_casos"] == 3  # incluye el de validación parcial
    assert r["metricas"]["k2"]["n_casos"] == 1
    assert r["metricas"]["checks"]["diferencias"]["v1 − v0"]["diferencia"] == pytest.approx(2 / 3)
    assert "juez" not in r["metricas"]  # sin juez de todas las opciones
    assert r["contrapeso"]["no_cotiza_indebidamente"]["opciones"]["v0"]["por_corrida"] == [1]
    assert r["contrapeso"]["no_deriva"]["opciones"]["reglas"]["por_corrida"] == [1]
    texto = cl.a_markdown(r, None, "abc1234", len(CASOS))
    assert "v1 − v0" in texto and "Contrapeso" in texto


def test_juez_solo_listos_con_veredicto_en_todas(monkeypatch, tmp_path):
    veredictos = {"j_v0": {"A": True, "B": None, "C": True}, "j_v1": {"A": True, "B": True, "C": True},
                  "j_r": {"A": False, "B": True, "C": False}}
    monkeypatch.setattr(cl, "juez_de_carpeta", lambda d: veredictos[d])
    run = _corrida(tmp_path, "x", {c["id"]: (True, {}) for c in CASOS})
    r = cl.comparar(CASOS, {"v0": [run], "v1": [run], "reglas": [run]},
                    {"v0": ["j_v0"], "v1": ["j_v1"], "reglas": ["j_r"]})
    # B no tiene veredicto en v0 y C es parcial: solo queda A
    assert r["metricas"]["juez"]["n_casos"] == 1


def test_correr_lote_falla_si_la_huella_no_coincide(tmp_path):
    falso = tmp_path / "lote.txt"
    falso.write_text("no es el lote", encoding="utf-8")
    with pytest.raises(SystemExit, match="SHA-256"):
        corr.main(["--lote", str(falso), "--salida", str(tmp_path / "s")])
