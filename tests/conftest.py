"""Configuración de pruebas: entorno aislado (sin tocar globex.db ni cotizaciones_pdf reales)."""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Valores de prueba: se fijan ANTES de importar main (load_dotenv no los sobrescribe).
os.environ["META_APP_SECRET"] = "secreto_de_prueba"
os.environ["DASHBOARD_API_KEY"] = "key_de_prueba"
os.environ["META_VERIFY_TOKEN"] = "verify_de_prueba"
os.environ["META_WABA_ID"] = "000"

# Credenciales falsas de Meta: aunque exista un .env real, ninguna prueba debe usarlas.
os.environ["META_ACCESS_TOKEN"] = "token_de_prueba"
os.environ["META_PHONE_NUMBER_ID"] = "000"

# main.py y pdf_generator.py crean globex.db y cotizaciones_pdf/ en el cwd.
_TMP = tempfile.mkdtemp(prefix="globex_tests_")
os.chdir(_TMP)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def bloquear_meta(monkeypatch):
    """Ninguna prueba sale a la Graph API: todo envío queda registrado en memoria."""
    import main

    enviados = []

    async def post_falso(payload):
        enviados.append(payload)
        return True

    monkeypatch.setattr(main, "_post_meta", post_falso)
    return enviados

