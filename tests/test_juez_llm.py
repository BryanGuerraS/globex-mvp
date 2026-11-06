"""LLM como juez (evaluacion/juez_llm.py), con un juez falso: no llama a Groq."""

import json

import pytest

from evaluacion import juez_llm as jz
from evaluacion import revision_humana as rh


def _respuesta(**cambios):
    datos = {c: {"motivo": "ok", "valor": "S"} for c in rh.CRITERIOS}
    for c, v in cambios.items():
        datos[c] = {"motivo": f"falla en {c}", "valor": v}
    return json.dumps(datos)


def test_prompt_incluye_rubrica_e_informacion_aprobada():
    p = jz.prompt_sistema()
    assert "C1 · Atiende la necesidad" in p and "Atención correcta" in p
    assert "## Procedimiento" not in p  # solo las secciones que necesita el juez
    assert "22.72 %" in p and "1 200" in p and "NO recalcules" in p
    assert all(c in p for c in rh.CRITERIOS)


def test_valida_y_normaliza_el_veredicto():
    v = jz.validar_veredicto(json.loads(_respuesta(C5_derivacion="N/A", C2_informacion="No")))
    assert v["C5_derivacion"]["valor"] == "NA" and v["C2_informacion"]["valor"] == "N"
    with pytest.raises(ValueError):
        jz.validar_veredicto(json.loads(_respuesta(C1_necesidad="NA")))  # NA solo en C5
    with pytest.raises(ValueError):
        jz.validar_veredicto({"C1_necesidad": {"valor": "S"}})  # faltan criterios
    con_tilde = json.loads(_respuesta())
    con_tilde["C5_derivación"] = con_tilde.pop("C5_derivacion")  # así lo escribió qwen
    assert jz.validar_veredicto(con_tilde)["C5_derivacion"]["valor"] == "S"


def test_reintenta_si_la_salida_no_es_valida():
    respuestas = iter(["no es json", "<think>pienso</think>" + _respuesta(C3_datos="N")])
    v = jz.juzgar("CLIENTE: hola", lambda m: next(respuestas), sistema="s")
    assert v["C3_datos"]["valor"] == "N"
    with pytest.raises(ValueError):
        jz.juzgar("CLIENTE: hola", lambda m: "{}", sistema="s")


def test_juzgar_hoja_genera_hoja_comparable_con_kappa(tmp_path):
    datos = {"resultados": {f"COT-{i:02d}": [{"chat_id": f"E{i}", "exito": i != 1,
                                              "turnos": [{"cliente": f"caso {i}", "respuestas": ["ok"]}]}]
                            for i in range(4)}}
    ruta = tmp_path / "resultados.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    rutas = rh.exportar(str(ruta), 4, str(tmp_path / "rev"))

    def juez_falso(mensajes):  # falla la conversación del caso 1
        return _respuesta(C2_informacion="N") if "caso 1" in mensajes[-1]["content"] else _respuesta()

    salida = str(tmp_path / "rev" / "hoja_juez.csv")
    jz.juzgar_hoja(rutas["A"], salida, juez_falso, avisar=lambda *_: None)
    juez = rh.leer_hoja(salida)
    assert set(juez) == set(rh.leer_hoja(rutas["A"]))
    assert sum(rh.atencion_correcta(f) == "N" for f in juez.values()) == 1
    assert "falla en C2_informacion" in " ".join(f["comentario"] for f in juez.values())

    checks = jz.comparar_con_checks(salida, rutas["clave"])
    assert checks is None or checks["coinciden"] == checks["n"]  # el JSON está en tmp, no en reportes


# ------------------------------------------------------------ errores sembrados

from evaluacion import errores_sembrados as es  # noqa: E402

COTIZACION = ("CLIENTE: Una laptop de 650 dólares que pesa 2.5 kg\n"
              "GLOBIX: [Proforma en imagen]\n• *Flete aéreo:* USD 22.50 (2.5 kg)\n"
              "GLOBIX: Total estimado: *USD 836.33*.")
FAQ = "CLIENTE: ¿Cuánto demora en llegar mi paquete?\nGLOBIX: ⏱️ *Plazos de entrega regulares:* 5 a 7 días hábiles."
SALUDO = "CLIENTE: Hola\nGLOBIX: ¡Hola! 👋 ¿En qué te ayudo?"


def test_cada_error_se_siembra_solo_donde_es_inequivoco():
    assert "(25.0 kg)" in es._peso_cambiado(COTIZACION)
    repetido = es._dato_repetido(COTIZACION).split("\n")
    assert repetido[1].startswith("GLOBIX: Antes de seguir") and repetido[2].startswith("GLOBIX: [Proforma")
    assert "descuento" in es._descuento(COTIZACION)
    assert es._no_atiende(FAQ).endswith("Otras consultas]") and "Plazos" not in es._no_atiende(FAQ)
    assert "asesor" in es._derivacion_innecesaria(FAQ).split("\n")[-1]
    # Un saludo no es una consulta estándar: no se siembran errores de necesidad ni derivación
    for fn in (es._no_atiende, es._derivacion_innecesaria, es._peso_cambiado, es._descuento):
        assert fn(SALUDO) is None


def test_deteccion_por_tipo():
    filas = [{"id": f"R{i}", "conversacion": t} for i, t in enumerate([COTIZACION, FAQ, SALUDO])]
    sembradas = es.sembrar(filas, 1)
    assert {s["tipo"] for s in sembradas} == set(es.TIPOS) and all(s["id"].startswith("S") for s in sembradas)
    juez = {}
    for s in sembradas:  # juez perfecto salvo en el plazo inventado
        v = {c: "S" for c in rh.CRITERIOS}
        if s["tipo"] != "plazo_inventado":
            v[s["criterio"]] = "N"
        juez[s["id"]] = v
    d = es.medir_deteccion(sembradas, juez)
    assert d["por_tipo"]["plazo_inventado"]["detectados"] == 0
    assert d["total"] == {"n": 6, "detectados": 5, "exactos": 5}
    assert "Total" in es.reporte(d, "modelo")
