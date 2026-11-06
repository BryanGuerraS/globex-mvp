"""Componente 5 del E3: el asesor valida la cotización (envía el PDF formal) o reporta errores."""

from fastapi.testclient import TestClient

import database
import main
import metricas
import pdf_generator
from pricing_engine import GlobexPricingEngine

client = TestClient(main.app)  # sin "with": no corre el startup (no llama a Meta)
API = {"X-API-Key": "key_de_prueba"}


def _chat_cotizado(chat_id: str, con_pdf: bool = True):
    calculo = GlobexPricingEngine.calcular(650, 2.5)
    database.registrar_mensaje_entrante(chat_id, "Perfil", "Laptop, USD 650, 2.5 kg")
    database.registrar_mensaje_saliente(chat_id, "bot", "Tu cotización", {"producto": "Laptop", **calculo})
    with database.get_connection() as conn:
        conn.execute("UPDATE chats SET cotizacion_total = ? WHERE chat_id = ?", (calculo["costo_total"], chat_id))
        conn.commit()
    if con_pdf:
        pdf_generator.generar_pdf_cotizacion(chat_id, "Ana", calculo)


def test_validar_envia_pdf_formal_y_registra(bloquear_meta):
    _chat_cotizado("rev-ok")
    r = client.post("/api/send-pdf", headers=API, json={"chat_id": "rev-ok", "nombre_asesor": "Bryan"})
    assert r.status_code == 200

    subida = [e for e in bloquear_meta if "subida_media" in e]
    assert subida and subida[0]["mime"] == "application/pdf"
    assert subida[0]["subida_media"] == main.NOMBRE_PDF_CLIENTE  # sin el ID del cliente en el nombre
    docs = [e for e in bloquear_meta if e.get("type") == "document"]
    assert docs and docs[0]["document"]["caption"] == main.TEXTO_PROFORMA_FORMAL

    chat = database.obtener_chat("rev-ok")
    assert chat["bot_activo"] == 0 and chat["asesor_asignado"] == "Bryan"
    revs = database.obtener_revisiones(chat_id="rev-ok")
    assert [r["tipo"] for r in revs] == [metricas.REVISION_VALIDADA]
    assert database.obtener_mensajes_chat("rev-ok")[-1]["emisor"] == "Bryan"


def test_sin_pdf_no_envia_ni_registra(bloquear_meta):
    _chat_cotizado("rev-sin-pdf", con_pdf=False)
    r = client.post("/api/send-pdf", headers=API, json={"chat_id": "rev-sin-pdf", "nombre_asesor": "Bryan"})
    assert r.status_code == 404
    assert bloquear_meta == [] and database.obtener_revisiones(chat_id="rev-sin-pdf") == []


def test_si_meta_falla_no_se_marca_validada(monkeypatch, bloquear_meta):
    async def falla(payload):
        return False

    monkeypatch.setattr(main, "_post_meta", falla)
    _chat_cotizado("rev-falla")
    r = client.post("/api/send-pdf", headers=API, json={"chat_id": "rev-falla", "nombre_asesor": "Bryan"})
    assert r.status_code == 502
    assert database.obtener_revisiones(chat_id="rev-falla") == []


def test_corregir_y_reportar_error():
    _chat_cotizado("rev-err", con_pdf=False)
    base = {"chat_id": "rev-err", "nombre_asesor": "Juan"}
    r = client.post("/api/revision", headers=API,
                    json={**base, "tipo": metricas.REVISION_CORREGIDA, "categoria": "dato_mal_extraido",
                          "nota": "  dijo 1.5 kg  "})
    assert r.status_code == 200

    id_bot = [m["id"] for m in database.obtener_mensajes_chat("rev-err") if m["emisor"] == "bot"][0]
    r = client.post("/api/revision", headers=API,
                    json={**base, "tipo": metricas.REVISION_ERROR, "categoria": "tono", "mensaje_id": id_bot})
    assert r.status_code == 200

    revs = database.obtener_revisiones(chat_id="rev-err")
    assert [(r["tipo"], r["categoria"]) for r in revs] == [
        (metricas.REVISION_CORREGIDA, "dato_mal_extraido"), (metricas.REVISION_ERROR, "tono")]
    assert revs[0]["nota"] == "dijo 1.5 kg" and revs[1]["mensaje_id"] == id_bot


def test_revision_rechaza_datos_invalidos():
    _chat_cotizado("rev-inv", con_pdf=False)
    database.registrar_mensaje_entrante("rev-sin-cot", "Perfil", "hola")
    base = {"chat_id": "rev-inv", "nombre_asesor": "Juan", "categoria": "tono"}
    casos = [
        {**base, "tipo": metricas.REVISION_VALIDADA},  # validar solo se hace enviando el PDF
        {**base, "tipo": metricas.REVISION_ERROR, "categoria": "inventada"},
        {**base, "tipo": metricas.REVISION_ERROR, "mensaje_id": 999999},
        {**base, "chat_id": "rev-sin-cot", "tipo": metricas.REVISION_CORREGIDA},
    ]
    for caso in casos:
        assert client.post("/api/revision", headers=API, json=caso).status_code == 422, caso
    assert client.post("/api/revision", headers=API,
                       json={**base, "chat_id": "no-existe", "tipo": metricas.REVISION_ERROR}).status_code == 404
    assert client.post("/api/revision", json={**base, "tipo": metricas.REVISION_ERROR}).status_code in (401, 403)


def test_resumen_cuenta_la_ultima_revision_por_chat():
    v, c, e = metricas.REVISION_VALIDADA, metricas.REVISION_CORREGIDA, metricas.REVISION_ERROR
    filas = [
        {"chat_id": "a", "tipo": c, "categoria": "dato_mal_extraido"},
        {"chat_id": "a", "tipo": v, "categoria": None},  # se corrigió y luego se validó
        {"chat_id": "b", "tipo": v, "categoria": None},
        {"chat_id": "c", "tipo": c, "categoria": "no_debio_cotizar"},
        {"chat_id": "d", "tipo": e, "categoria": "tono"},
    ]
    res = metricas.resumir_revisiones(filas)
    assert res["cotizaciones_revisadas"] == 3 and res["cotizaciones_validadas"] == 2
    assert res["errores_reportados"] == 3
    li, ls = res["ic95"]
    assert li < 2 / 3 < ls
    assert metricas.resumir_revisiones([])["porcentaje_validadas"] is None


def test_metricas_incluye_revisiones():
    datos = client.get("/api/metricas", headers=API, params={"horas": 0}).json()
    assert "cotizaciones_revisadas" in datos["revisiones"]
