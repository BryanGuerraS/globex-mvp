"""Pruebas de las reglas del motor: mínimo de 1 kg y tope de USD 1 200."""

import pytest

from pricing_engine import GlobexPricingEngine as E


@pytest.mark.parametrize("peso", [0.1, 0.45, 0.99, 1.0])
def test_bajo_1kg_se_cobra_1kg(peso):
    r = E.calcular(100, peso)
    assert r["peso_facturable_kg"] == 1.0
    assert r["costo_flete"] == 9.0
    assert r["costo_envio"] == 18.0
    assert r["peso_kg"] == peso  # el peso real se conserva


def test_sobre_1kg_es_proporcional():
    r = E.calcular(100, 2.5)
    assert r["peso_facturable_kg"] == 2.5
    assert r["costo_envio"] == 31.5


def test_mensaje_avisa_minimo():
    msg = E.formatear_mensaje_whatsapp(E.calcular(100, 0.45))
    assert "0.45 kg, se cobra el mínimo de 1 kg" in msg


def test_mensaje_sin_aviso_sobre_1kg():
    assert "mínimo" not in E.formatear_mensaje_whatsapp(E.calcular(100, 2))


@pytest.mark.parametrize("valor, deriva", [(1199.99, False), (1200, False), (1200.01, True), (5000, True)])
def test_tope_1200(valor, deriva):
    assert E.requiere_asesor(valor) is deriva
