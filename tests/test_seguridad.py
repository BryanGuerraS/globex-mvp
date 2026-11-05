"""Pruebas del hallazgo 1 (seguridad): API key, firma de Meta, verify token y PDFs."""

import hashlib
import hmac
import json
import os

from fastapi.testclient import TestClient

import main
import pdf_generator

client = TestClient(main.app)  # sin "with": no corre el startup (no llama a Meta)
API_OK = {"X-API-Key": "key_de_prueba"}


def _firmar(cuerpo: bytes, secreto: str = "secreto_de_prueba") -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


# ---------- /api/* ----------

def test_api_sin_key_rechaza():
    assert client.get("/api/chats").status_code == 401


def test_api_key_incorrecta_rechaza():
    r = client.get("/api/chats", headers={"X-API-Key": "otra"})
    assert r.status_code == 401


def test_api_key_correcta_permite():
    assert client.get("/api/chats", headers=API_OK).status_code == 200


def test_clean_data_sin_key_rechaza():
    assert client.post("/api/admin/clean-data").status_code == 401


def test_todas_las_rutas_api_protegidas():
    rutas = [
        r for r in main.app.routes if getattr(r, "path", "").startswith("/api/")
    ]
    assert rutas
    for ruta in rutas:
        deps = [d.call for d in ruta.dependant.dependencies]
        assert main.verificar_api_key in deps, ruta.path


def test_api_sin_key_configurada_falla_cerrado(monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_API_KEY", None)
    assert client.get("/api/chats", headers=API_OK).status_code == 503


# ---------- Webhook de Meta ----------

def test_test_chiquito_eliminado():
    assert client.post("/test-chiquito", json={}).status_code in (404, 405)


def test_webhook_sin_firma_rechaza():
    assert client.post("/meta-webhook", json={"entry": []}).status_code == 403


def test_webhook_firma_incorrecta_rechaza():
    cuerpo = json.dumps({"entry": []}).encode()
    r = client.post(
        "/meta-webhook",
        content=cuerpo,
        headers={"X-Hub-Signature-256": _firmar(cuerpo, "otro_secreto")},
    )
    assert r.status_code == 403


def test_webhook_firma_correcta_acepta():
    # Evento de estado (sin "messages"): no dispara LLM ni envíos.
    cuerpo = json.dumps(
        {"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}
    ).encode()
    r = client.post(
        "/meta-webhook",
        content=cuerpo,
        headers={"X-Hub-Signature-256": _firmar(cuerpo)},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "event_without_messages"}


def test_webhook_sin_app_secret_falla_cerrado(monkeypatch):
    monkeypatch.setattr(main, "META_APP_SECRET", None)
    cuerpo = b"{}"
    r = client.post(
        "/meta-webhook", content=cuerpo, headers={"X-Hub-Signature-256": _firmar(cuerpo)}
    )
    assert r.status_code == 403


def test_verify_token_correcto():
    r = client.get(
        "/meta-webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify_de_prueba", "hub.challenge": "123"},
    )
    assert r.status_code == 200 and r.text == "123"


def test_verify_sin_token_configurado_rechaza(monkeypatch):
    monkeypatch.setattr(main, "META_VERIFY_TOKEN", None)
    r = client.get("/meta-webhook", params={"hub.mode": "subscribe", "hub.challenge": "1"})
    assert r.status_code == 403


def test_verify_token_incorrecto_rechaza():
    r = client.get(
        "/meta-webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"},
    )
    assert r.status_code == 403


# ---------- PDFs ----------

def _crear_pdf_vacio(nombre: str):
    os.makedirs(pdf_generator.PDF_DIR, exist_ok=True)
    open(os.path.join(pdf_generator.PDF_DIR, nombre), "wb").close()


def test_nombre_pdf_no_contiene_telefono():
    ruta = pdf_generator.generar_pdf_cotizacion(
        "51900000001",
        "Cliente Prueba",
        {"valor_producto": 50.0, "peso_kg": 1.0, "tributos_aprox": 0.0, "costo_total": 68.0},
    )
    assert "51900000001" not in os.path.basename(ruta)
    assert pdf_generator.buscar_ultimo_pdf("51900000001") == ruta


def test_buscar_pdf_no_confunde_prefijos():
    # Un chat cuyo número es prefijo de otro no debe recibir el PDF ajeno.
    otro = f"Proforma_Globex_{pdf_generator.id_archivo_chat('51900000002999')}_20260101_120000.pdf"
    _crear_pdf_vacio(otro)
    assert pdf_generator.buscar_ultimo_pdf("51900000002") is None


def test_buscar_pdf_devuelve_el_mas_reciente():
    h = pdf_generator.id_archivo_chat("51900000003")
    _crear_pdf_vacio(f"Proforma_Globex_{h}_20260101_120000.pdf")
    _crear_pdf_vacio(f"Proforma_Globex_{h}_20260102_120000.pdf")
    assert pdf_generator.buscar_ultimo_pdf("51900000003").endswith("20260102_120000.pdf")


def test_descarga_pdf_requiere_key_y_funciona():
    h = pdf_generator.id_archivo_chat("51900000004")
    _crear_pdf_vacio(f"Proforma_Globex_{h}_20260101_120000.pdf")
    assert client.get("/api/download-pdf/51900000004").status_code == 401
    r = client.get("/api/download-pdf/51900000004", headers=API_OK)
    assert r.status_code == 200
    assert "51900000004" not in r.headers.get("content-disposition", "")
