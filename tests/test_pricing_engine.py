"""Pruebas de las reglas del motor: mínimo de 1 kg, TAX de tienda, tributos 24 % y tope de USD 2 000."""

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


@pytest.mark.parametrize("valor, tax, deriva", [
    (1500, None, False), (1869.16, None, False), (1869.17, None, True), (1999.99, None, True),
    (1999.99, 0, False), (2000, 0, False), (2000.01, 0, True), (5000, 0, True),
])
def test_tope_2000_sobre_producto_mas_tax(valor, tax, deriva):
    assert E.requiere_asesor(valor, tax) is deriva


def test_ejemplo_del_excel():
    """Formato Cotizacion (5).xlsx, hoja COURIER: iPhone USD 1 199, 1 kg (trámite USD 9 en vez de 7)."""
    r = E.calcular(1199, 1)
    assert (r["tax_tienda"], r["boleta"], r["tributos_aprox"]) == (83.93, 1282.93, 307.90)
    assert r["costo_total"] == 1608.83 and r["tax_estimado"]


def test_tax_del_cliente_y_sin_tax():
    assert E.calcular(650, 2.5, 45.5)["tax_tienda"] == 45.5
    r = E.calcular(199.99, 1, 0)
    assert r["tax_tienda"] == 0 and not r["aplica_impuesto"] and not r["tax_estimado"]
    with pytest.raises(ValueError):
        E.calcular(100, 1, -1)


def test_mensaje_muestra_tax():
    assert "*TAX de la tienda:* USD 45.50 (estimado 7 %)" in E.formatear_mensaje_whatsapp(E.calcular(650, 2.5))
    assert "USD 0.00 (incluido en el precio)" in E.formatear_mensaje_whatsapp(E.calcular(650, 2.5, 0))
    assert "TAX de la tienda:* USD 45.50" + chr(10) in E.formatear_mensaje_whatsapp(E.calcular(650, 2.5, 45.5))


def test_cantidad_en_lineas_aparte_con_valor_unitario():
    msg = E.formatear_mensaje_whatsapp(E.calcular(20, 1, cantidad=3))
    assert "• *Valor unitario:* USD 20.00\n• *Cantidad:* 3\n• *Total:* USD 60.00\n" in msg
    uno = E.formatear_mensaje_whatsapp(E.calcular(20, 1))
    assert "Cantidad" not in uno and "Valor unitario" not in uno
