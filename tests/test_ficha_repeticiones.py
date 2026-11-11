"""Ficha de la clase con varias corridas (evaluacion/ficha_repeticiones.py)."""

import pytest

from evaluacion import ficha_repeticiones as fr

IDS = ["a", "b", "c", "d"]
CASOS = [{"id": i} for i in IDS]


def test_resumen_de_corridas_promedio_minimo_maximo():
    corridas = [{"a": True, "b": True, "c": False, "d": False},   # 50 %
                {"a": True, "b": True, "c": True, "d": False},    # 75 %
                {"a": True, "b": False, "c": False, "d": False}]  # 25 %
    r = fr.resumen_corridas(corridas, IDS)
    assert r["promedio"] == pytest.approx(0.5) and (r["minimo"], r["maximo"]) == (0.25, 0.75)
    assert [t["exitos"] for t in r["corridas"]] == [2, 3, 1]


def test_sin_veredicto_no_cuenta_en_el_denominador():
    t = fr.tasa({"a": True, "b": None, "c": False, "d": True}, IDS)
    assert (t["exitos"], t["n"]) == (2, 3)


def test_ficha_compara_juez_solo_en_casos_con_veredicto_del_baseline():
    v0 = [{"a": True, "b": True, "c": True, "d": False}]
    base_juez = {"a": False, "b": True, "c": None, "d": False}  # sin veredicto en "c"
    texto = fr.ficha(CASOS, None, v0, [{"a": True, "b": True, "c": True, "d": False}],
                     {"a": False, "b": True, "c": True, "d": False}, base_juez)
    assert "| Éxito de tarea (checks) | 50.0 % (2/4) | 75.0 % | +25.0 pp |" in texto
    # juez sobre a, b, d: Globix 2/3, reglas 1/3
    assert "| Atención correcta (juez) | 33.3 % (1/3) | 66.7 % | +33.3 pp |" in texto


def test_exito_de_csv(tmp_path):
    ruta = tmp_path / "oficial.csv"
    ruta.write_text("a;✅\nb;❌\n", encoding="utf-8")
    assert fr.exito_de_csv(str(ruta)) == {"a": True, "b": False}
