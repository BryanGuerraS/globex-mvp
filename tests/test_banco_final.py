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
    assert resumen["meta"] == 90 and resumen["meta_del_banco"] == 95
    derivacion = next(k for k in resultado["kpis"] if k["indicador"] == "Derivación correcta")
    assert derivacion["meta"] == 80 and derivacion["meta_del_banco"] == 90
