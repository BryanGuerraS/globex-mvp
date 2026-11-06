"""Revisión humana doble (docs/rubrica_calidad.md): etiquetas, kappa, muestra y consenso."""

import json

import pytest

from evaluacion import revision_humana as rh


def test_normalizar_acepta_variantes():
    assert [rh.normalizar(v) for v in ("Sí", " s ", "1", "no", "N", "N/A", "no aplica", "")] == \
        ["S", "S", "S", "N", "N", "NA", "NA", None]
    with pytest.raises(ValueError):
        rh.normalizar("tal vez")


def test_atencion_correcta():
    base = {c: "S" for c in rh.CRITERIOS}
    assert rh.atencion_correcta(base) == "S"
    assert rh.atencion_correcta({**base, "C5_derivacion": "NA"}) == "S"
    assert rh.atencion_correcta({**base, "C6_claridad": "N"}) == "S"  # la claridad va aparte
    assert rh.atencion_correcta({**base, "C2_informacion": "N"}) == "N"
    assert rh.atencion_correcta({**base, "C3_datos": None}) is None


def test_kappa_cohen():
    # p_o = 0.75; p_e = 0.5·0.25 + 0.5·0.75 = 0.5 -> kappa = 0.5
    assert rh.kappa_cohen(list("SSNN"), list("SNNN")) == pytest.approx(0.5)
    assert rh.kappa_cohen(list("SNSN"), list("SNSN")) == pytest.approx(1.0)
    assert rh.kappa_cohen(list("SSSS"), list("SSSS")) is None  # una sola categoría: no definido
    # Ejemplo clásico (Cohen): 20 SS, 5 SN, 10 NS, 15 NN -> kappa = 0.4
    a = ["S"] * 25 + ["N"] * 25
    b = ["S"] * 20 + ["N"] * 5 + ["S"] * 10 + ["N"] * 15
    assert rh.kappa_cohen(a, b) == pytest.approx(0.4)
    li, ls = rh.ic_bootstrap_kappa(a, b)
    assert li < 0.4 < ls


def test_muestra_estratificada_y_reproducible():
    ids = [f"COT-{i:02d}" for i in range(40)] + [f"FAQ-{i:02d}" for i in range(10)] + ["SEG-01"]
    m = rh.elegir_muestra(ids, 20)
    assert len(m) == 20 and m == rh.elegir_muestra(ids, 20)
    por_tipo = {t: sum(x.startswith(t) for x in m) for t in ("COT", "FAQ", "SEG")}
    assert por_tipo["SEG"] == 1 and por_tipo["COT"] > por_tipo["FAQ"] >= 1


def _resultados(tmp_path, n=6):
    datos = {"resultados": {
        f"{'COT' if i % 2 else 'FAQ'}-{i:02d}": [{"chat_id": f"EVAL-{i}", "turnos": [
            {"cliente": f"hola {i}", "respuestas": [f"respuesta {i}"]}]}]
        for i in range(n)}}
    ruta = tmp_path / "resultados.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def _llenar(ruta, valores_por_id):
    filas = rh.leer_csv(ruta)
    for f in filas:
        f.update(valores_por_id.get(f["id"], {}))
    rh.escribir_csv(ruta, rh.COLUMNAS_HOJA, filas)


def test_flujo_completo_exportar_kappa_consenso(tmp_path):
    rutas = rh.exportar(str(_resultados(tmp_path)), 6, str(tmp_path / "rev"))
    hoja_a = rh.leer_csv(rutas["A"])
    assert len(hoja_a) == 6 and "CLIENTE: hola" in hoja_a[0]["conversacion"]
    assert "COT" not in rutas["A"] and all(not f["C1_necesidad"] for f in hoja_a)  # sin tipo ni etiquetas
    assert {f["caso"] for f in rh.leer_csv(rutas["clave"])} == {f"{'COT' if i % 2 else 'FAQ'}-{i:02d}" for i in range(6)}

    todo_si = {c: "S" for c in rh.CRITERIOS}
    ids = [f["id"] for f in hoja_a]
    _llenar(rutas["A"], {i: todo_si for i in ids})
    _llenar(rutas["B"], {i: ({**todo_si, "C2_informacion": "N"} if i == ids[0] else todo_si) for i in ids})

    a, b = rh.leer_hoja(rutas["A"]), rh.leer_hoja(rutas["B"])
    acuerdo = rh.medir_acuerdo(a, b)
    assert acuerdo["n"] == 6 and acuerdo["criterios"]["atencion_correcta"]["acuerdo"] == pytest.approx(5 / 6)
    disc = rh.discrepancias(a, b)
    assert [(d["id"], d["criterio"]) for d in disc] == [(ids[0], "C2_informacion")]

    with pytest.raises(ValueError):
        rh.aplicar_consenso(a, b, disc)  # falta escribir el consenso
    disc[0]["consenso"] = "N"
    clave = {f["id"]: f for f in rh.leer_csv(rutas["clave"])}
    final = rh.resultado_final(rh.aplicar_consenso(a, b, disc), clave)
    total = final["total"]["atencion_correcta"]
    assert (total["exitos"], total["n"]) == (5, 6) and total["ic95"][0] < 5 / 6 < total["ic95"][1]
    assert set(final["por_categoria"]) == {"COT", "FAQ"}
    assert "Atención correcta" in rh.reporte_markdown(acuerdo, final)


def test_hoja_rechaza_na_fuera_de_c5(tmp_path):
    rutas = rh.exportar(str(_resultados(tmp_path, 2)), 2, str(tmp_path / "rev"))
    rid = rh.leer_csv(rutas["A"])[0]["id"]
    _llenar(rutas["A"], {rid: {c: "S" for c in rh.CRITERIOS} | {"C1_necesidad": "NA"}})
    with pytest.raises(ValueError, match="NA solo se permite en C5"):
        rh.leer_hoja(rutas["A"])


def test_lee_csv_con_coma_de_google_sheets(tmp_path):
    ruta = tmp_path / "hoja.csv"
    ruta.write_text("id,conversacion," + ",".join(rh.CRITERIOS) + ",comentario\nR001,x," +
                    ",".join(["Sí"] * 5 + ["No"]) + ",ok\n", encoding="utf-8")
    hoja = rh.leer_hoja(str(ruta))
    assert hoja["R001"]["C1_necesidad"] == "S" and hoja["R001"]["C6_claridad"] == "N"
