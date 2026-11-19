"""Endpoint del banco final: banco sintético mínimo (no el real), LLM y juez simulados."""

import asyncio
import hashlib
import io
import json
import zipfile

import pytest

import main
from tests.test_eval_api import KEY, api  # noqa: F401  (fixture)
from tests.test_tool_calling import _respuesta

ARCHIVOS = {
    "00_Indice_Bancos.txt": json.dumps({"version_paquete": "PRUEBA_V1", "bancos": [
        {"banco": "FAQ", "banco_id": "FAQ_1", "ids_previstos": ["FAQ001"], "meta": 80},
        {"banco": "DERIVACION", "banco_id": "DER_1", "ids_previstos": ["DER001"], "meta": 90},
        {"banco": "PRODUCTOS", "banco_id": "PRO_1", "ids_previstos": ["PRO001"], "meta": 80,
         "ids_bloqueados_previstos": ["PRO001"]},
        {"banco": "COTIZACIONES", "banco_id": "COT_1", "ids_previstos": ["U01-01"], "meta": 95},
        {"banco": "CHATS_COMPARTIDOS", "banco_id": "CH_1", "ids_previstos": ["CHAT001"],
         "metas": {"recopilacion": 90, "resumen": 95}}]}),
    "02_FAQ/Preguntas.txt": "ID: FAQ001\n¿Cuánto demora el envío?\n",
    "03_Derivacion/Preguntas.txt": "ID: DER001\nQuiero hablar con una persona\n",
    "04_Productos_Especiales/Preguntas.txt": "ID: PRO001\nQuiero traer un vape\n",
    "06_Cotizaciones/Cotizaciones.txt": "ID: U01-01\nUn libro de USD 40,00, TAX USD 0,00, pesa 1 kg\n",
    "05_Chats_Recopilacion_Resumen/Chats.txt": "ID: CHAT001\nUNIVERSO: CH01\nMENSAJE 1: Hola, soy Ana\nMENSAJE 2: Quiero un asesor\n",
    "02_FAQ/Respuestas_con_Rubrica/U01.txt": "ID: FAQ001\nRESPUESTA ORIENTATIVA\n5 días hábiles\n",
    "03_Derivacion/Respuestas_con_Rubrica.txt": "ID: DER001\nREQUIERE DERIVACIÓN: SÍ.\n",
    "04_Productos_Especiales/Respuestas_con_Rubrica/01.txt": "ID: PRO001\nCONDICIÓN: NO_ADMITIDO\n",
    "06_Cotizaciones/Respuestas_Cotizaciones.txt": "ID: U01-01\nTOTAL ESPERADO: USD 58,00\n",
    "05_Chats_Recopilacion_Resumen/Respuestas_Recopilacion_con_Rubrica.txt": "ID: CHAT001\nD001 nombre Ana\n",
    "05_Chats_Recopilacion_Resumen/Respuestas_Resumen_con_Rubrica.txt": "ID: CHAT001\nResumen esperado\n",
    **{f"01_System_Prompts/{n}": "Prompt de prueba" for n in (
        "01_Calidad_FAQ.txt", "03_Productos_Especiales.txt", "07_Chats_Conjunto.txt")},
}


def _zip(alterar=False) -> bytes:
    archivos = {f"Globex_Bancos_V2/{k}": v.encode("utf-8") for k, v in ARCHIVOS.items()}
    manifiesto = "\n".join(f"{hashlib.sha256(v).hexdigest()}  {k.split('/', 1)[1]}" for k, v in archivos.items())
    archivos["Globex_Bancos_V2/MANIFIESTO_SHA256.txt"] = manifiesto.encode("utf-8")
    if alterar:
        archivos["Globex_Bancos_V2/02_FAQ/Preguntas.txt"] = b"ID: FAQ001\nOtra pregunta\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in archivos.items():
            z.writestr(k, v)
    return buf.getvalue()


VEREDICTO = json.dumps({"casos": [{"aceptable": True, "avance_indebido_a_cotizacion": False}],
                        "recopilacion": {"casos": [{"porcentaje": 100}]},
                        "resumen": {"casos": [{"aceptable_para_kpi": True}]}})


@pytest.fixture
def banco(api, monkeypatch):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(content="Respuesta de prueba 😊")] * 20)
    main._trabajos_banco.clear()
    lanzados = []
    monkeypatch.setattr(main, "_en_segundo_plano", lambda corrutina: lanzados.append(corrutina))
    import sys
    sys.path.insert(0, "evaluacion")
    import juez_banco
    monkeypatch.setattr(juez_banco, "destinos_pago", lambda entorno: [("cerebras", "url", "key", "m", 10)])
    monkeypatch.setattr(juez_banco.Juez, "__call__", lambda self, sistema, usuario: VEREDICTO)
    return cliente, lanzados


def test_corre_el_banco_y_genera_el_informe(banco):
    cliente, lanzados = banco
    r = cliente.post("/api/eval/banco-final", headers={**KEY, "Content-Type": "application/zip"}, content=_zip())
    assert r.status_code == 202 and r.json()["casos"] == 5
    trabajo_id = r.json()["trabajo_id"]
    # mientras corre, no se puede lanzar otra corrida
    assert cliente.post("/api/eval/banco-final", headers=KEY, content=_zip()).status_code == 409
    asyncio.run(lanzados[0])
    estado = cliente.get(f"/api/eval/banco-final/{trabajo_id}", headers=KEY).json()
    assert estado["estado"] == "listo", estado.get("error")
    assert estado["casos_hechos"] == 5 and estado["juez_total"] == 3
    indicadores = {k["indicador"]: k for k in estado["resultado"]["kpis"]}
    assert indicadores["Calidad de respuesta a preguntas frecuentes"]["porcentaje"] == 100.0
    assert indicadores["Exactitud y completitud de los datos recopilados"]["porcentaje"] == 100
    informe = cliente.get(f"/api/eval/banco-final/{trabajo_id}/informe", headers=KEY)
    assert informe.status_code == 200 and "# Informe del banco final" in informe.text
    assert "| Exactitud del total cotizado |" in informe.text and "(verificado)" in informe.text
    casos = cliente.get(f"/api/eval/banco-final/{trabajo_id}/resultados", headers=KEY)
    assert len(casos.text.strip().splitlines()) == 5


def test_rechaza_un_banco_alterado_o_sin_key(banco):
    cliente, _ = banco
    assert cliente.post("/api/eval/banco-final", content=_zip()).status_code == 401
    r = cliente.post("/api/eval/banco-final", headers=KEY, content=_zip(alterar=True))
    assert r.status_code == 422 and "manifiesto" in r.json()["detail"]
    assert cliente.post("/api/eval/banco-final", headers=KEY, content=b"no es un zip").status_code == 422


def test_evaluacion_py_de_punta_a_punta(banco, tmp_path, monkeypatch):
    """evaluacion.py: verifica la carpeta, corre los casos y el juez por la API y genera el PDF."""
    import importlib.util
    import sys
    cliente, _ = banco
    carpeta = tmp_path / "Globex_Bancos_V2"
    with zipfile.ZipFile(io.BytesIO(_zip())) as z:
        z.extractall(tmp_path)
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("evaluacion_cli", repo / "evaluacion.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "RAIZ", tmp_path)
    monkeypatch.setenv("EVAL_API_KEY", "clave_eval_prueba")

    class ServidorPrueba(cli.Servidor):
        def __init__(self, url, key):
            self.url, self.http = "", cliente
            cliente.headers.update({"X-API-Key": key})

    monkeypatch.setattr(cli, "Servidor", ServidorPrueba)
    monkeypatch.setattr(sys, "argv", ["evaluacion.py", str(carpeta), "--corrida", "PRUEBA1"])
    cli.main()
    destino = tmp_path / "evaluacion" / "reportes" / "banco_final" / "PRUEBA1"
    resultado = json.loads((destino / "resultado.json").read_text(encoding="utf-8"))
    assert resultado["meta"]["ejecutados"] == 5 and (destino / "Informe_final_PRUEBA1.pdf").stat().st_size > 2000
    resumen = next(k for k in resultado["kpis"] if k["indicador"] == "Calidad del resumen para el asesor")
    assert resumen["meta"] == 85 and "meta_del_banco" not in resumen
    derivacion = next(k for k in resultado["kpis"] if k["indicador"] == "Derivación correcta")
    assert derivacion["meta"] == 80

    # Con --repeticiones: reutiliza la corrida hecha, agrega -R2 y el informe con promedio y rango
    monkeypatch.setattr(sys, "argv", ["evaluacion.py", str(carpeta), "--corrida", "PRUEBA1", "--repeticiones", "2"])
    cli.main()
    combinado = tmp_path / "evaluacion" / "reportes" / "banco_final" / "PRUEBA1-x2"
    res2 = json.loads((combinado / "resultado.json").read_text(encoding="utf-8"))
    assert res2["meta"]["corridas"] == ["PRUEBA1", "PRUEBA1-R2"] and res2["meta"]["ejecutados"] == 10
    assert (combinado / "Informe_final_PRUEBA1-x2.pdf").stat().st_size > 2000
    for k in res2["kpis"]:
        assert len(k["por_corrida"]) == 2
        if k["porcentaje"] is not None:
            assert k["minimo"] <= k["porcentaje"] <= k["maximo"] and k["cumple"] == (k["porcentaje"] >= k["meta"])


def test_combinar_kpis_promedio_y_rango():
    import banco_final
    a = [{"indicador": "X", "meta": 80, "porcentaje": 90.0, "aciertos": 9, "casos": 10, "cumple": True}]
    b = [{"indicador": "X", "meta": 80, "porcentaje": 70.0, "aciertos": 7, "casos": 10, "cumple": False}]
    c = [{"indicador": "X", "meta": 80, "porcentaje": 83.0, "aciertos": 8, "casos": 10, "cumple": True}]
    k = banco_final.combinar_kpis([a, b, c])[0]
    assert (k["porcentaje"], k["minimo"], k["maximo"]) == (81.0, 70.0, 90.0)
    assert k["cumple"] and k["corridas_que_cumplen"] == 2


def test_segmentos_por_universo_y_tipo_de_pedido():
    import banco_final
    banco = {"ids_bloqueados_productos": ["PRO002"], "casos": [
        {"id": "U01-01", "banco": "COTIZACIONES"}, {"id": "U01-02", "banco": "COTIZACIONES"},
        {"id": "U02-01", "banco": "COTIZACIONES"}, {"id": "PRO001", "banco": "PRODUCTOS"},
        {"id": "PRO002", "banco": "PRODUCTOS"}, {"id": "CHAT001", "banco": "CHATS_COMPARTIDOS", "universo": "CH01"}]}
    kpis = [{"indicador": "Exactitud del total cotizado", "fallas": ["U01-02"]},
            {"indicador": "Calidad de respuesta sobre productos con condiciones especiales", "fallas": ["PRO002"]},
            {"indicador": "Calidad del resumen para el asesor", "fallas": []}]
    seg = {(s["banco"], s["segmento"]): s for s in banco_final.segmentos(kpis, banco)}
    assert seg[("COTIZACIONES", "Universo U01")]["aciertos"] == 1 and seg[("COTIZACIONES", "Universo U01")]["casos"] == 2
    assert seg[("PRODUCTOS", "Pedido no cotizable")]["fallas"] == ["PRO002"]
    assert seg[("CHATS_COMPARTIDOS", "Universo CH01")]["porcentaje"] == 100.0
    dos = banco_final.combinar_segmentos([list(seg.values()), list(seg.values())])
    u01 = next(s for s in dos if s["segmento"] == "Universo U01")
    assert (u01["aciertos"], u01["casos"]) == (2, 4)


def test_comparar_globix_con_reglas():
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("baseline_bf", repo / "evaluacion" / "baseline_banco_final.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    globix = [{"indicador": "A", "porcentaje": 90.0, "meta": 85}, {"indicador": "B", "porcentaje": None, "meta": 80}]
    reglas = [{"indicador": "A", "porcentaje": 60.5, "cumple": False}, {"indicador": "B", "porcentaje": 50.0, "cumple": False}]
    comp = {c["indicador"]: c for c in mod.comparar(globix, reglas)}
    assert comp["A"]["diferencia_pp"] == 29.5 and comp["B"]["diferencia_pp"] is None
    # Varias corridas: se resta el promedio sin redondear (98.89 - 47.85 = 51.0, no 98.9 - 47.85 = 51.1)
    combinado = [{"indicador": "C", "porcentaje": 98.9, "por_corrida": [99.05, 99.05, 98.57], "meta": 90}]
    assert mod.comparar(combinado, [{"indicador": "C", "porcentaje": 47.85}])[0]["diferencia_pp"] == 51.0


def _cli(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("evaluacion_cli_bancos", repo / "evaluacion.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "RAIZ", tmp_path)
    monkeypatch.setattr(cli, "BANCOS", tmp_path / "bancos")
    (tmp_path / "bancos").mkdir()
    return cli


def test_evaluacion_py_encuentra_el_banco_en_la_carpeta_bancos(tmp_path, monkeypatch):
    """Sin ruta, usa el zip (o la carpeta) que esté en bancos/; con dos o ninguno, avisa."""
    cli = _cli(tmp_path, monkeypatch)
    with pytest.raises(cli.banco_final.BancoInvalido, match="No hay ningún zip"):
        cli.ubicar_banco()
    (tmp_path / "bancos" / "Globex_Bancos_V2_entrega.zip").write_bytes(_zip())
    carpeta, banco, sha = cli.ubicar_banco()
    assert (carpeta / "00_Indice_Bancos.txt").exists() and len(banco["casos"]) == 5 and len(sha) == 64
    (tmp_path / "bancos" / "otro.zip").write_bytes(_zip())
    with pytest.raises(Exception, match="más de un banco"):
        cli.ubicar_banco()
    # Carpeta descomprimida (también la de afuera del zip) o ruta directa al zip
    for z in (tmp_path / "bancos").glob("*.zip"):
        z.unlink()
    with zipfile.ZipFile(io.BytesIO(_zip())) as z:
        z.extractall(tmp_path / "bancos" / "Globex_Bancos_Prompts_Compactos")
    assert cli.ubicar_banco()[2] == sha
    assert cli.ubicar_banco(str(tmp_path / "bancos" / "Globex_Bancos_Prompts_Compactos"))[2] == sha
    (tmp_path / "x.zip").write_bytes(_zip(alterar=True))
    with pytest.raises(Exception, match="manifiesto"):
        cli.ubicar_banco(str(tmp_path / "x.zip"))


def test_evaluacion_py_crea_el_env_con_la_plantilla(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    monkeypatch.delenv("EVAL_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="Se creó"):
        cli.leer_key()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "EVAL_API_KEY=PON_TU_CLAVE_AQUI\n"
    with pytest.raises(SystemExit, match="reemplaza PON_TU_CLAVE_AQUI"):
        cli.leer_key()
    monkeypatch.delenv("EVAL_API_KEY", raising=False)
    (tmp_path / ".env").write_text("EVAL_API_KEY=clave_de_prueba\n", encoding="utf-8")
    assert cli.leer_key() == "clave_de_prueba"
