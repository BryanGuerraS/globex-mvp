"""Cotización de pedidos con varios productos y tiendas (reglas del 14/11/2026)."""

import pytest

import main
from pricing_engine import GlobexPricingEngine as E
from tests.test_tool_calling import _respuesta, _tool_call, entorno  # noqa: F401
from tests.utilidades import texto_bot_registrado
from validaciones import validar_productos

POLOS = {"producto": "Polos", "tienda": "Amazon", "precio_unitario": 20, "cantidad": 2, "peso_kg": 1}
NIKE = {"producto": "Zapatillas Nike", "precio_unitario": 120, "peso_kg": 1.5}


def test_ejemplo_aprobado_bajo_200_sin_tributos():
    r = E.calcular_pedido([POLOS, NIKE])
    # 40 + 2.80 = 42.80; 120 + 8.40 = 128.40; suma 171.20 < 200; 2.5 kg × 9 = 22.50; + 9 de desaduanaje
    assert [p["total"] for p in r["productos"]] == [42.80, 128.40]
    assert (r["boleta"], r["costo_flete"], r["tributos_aprox"], r["costo_total"]) == (171.20, 22.50, 0.0, 202.70)


def test_tributos_sobre_la_suma_y_un_solo_desaduanaje():
    r = E.calcular_pedido([POLOS, NIKE, {"producto": "Perfume", "precio_unitario": 85, "peso_kg": 0.6, "tax": 0}])
    assert r["boleta"] == 256.20 and r["aplica_impuesto"] and r["tributos_aprox"] == 61.49
    assert r["costo_envio"] - r["costo_flete"] == pytest.approx(9.0)
    assert r["costo_total"] == 354.59


def test_peso_total_con_minimo_de_1_kg():
    r = E.calcular_pedido([{"precio_unitario": 10}, {"precio_unitario": 15}], peso_total_kg=0.4)
    assert r["peso_facturable_kg"] == 1.0 and r["costo_flete"] == 9.0
    with pytest.raises(ValueError):
        E.calcular_pedido([{"precio_unitario": 10}])  # sin peso


def test_tope_sobre_la_suma_del_pedido():
    assert not E.requiere_asesor_pedido([{"precio_unitario": 900, "tax": 0}, {"precio_unitario": 1100, "tax": 0}])
    assert E.requiere_asesor_pedido([{"precio_unitario": 900}, {"precio_unitario": 1100, "tax": 0}])  # 900 × 1.07


def test_un_producto_da_lo_mismo_que_calcular():
    a = E.calcular(650, 2.5, None, 1)
    b = E.calcular_pedido([{"precio_unitario": 650, "peso_kg": 2.5}])
    assert {k: b[k] for k in a} == a


def test_validacion_ancla_cada_producto():
    textos = ["2 polos de amazon de 20 dólares cada uno, 1 kg, y unas zapatillas nike de 120 dólares de 1.5 kg"]
    ok = validar_productos({"productos": [
        {"producto": "polos", "tienda": "Amazon", "precio_unitario_usd": 20, "cantidad": 2, "peso_kg": 1},
        {"producto": "zapatillas", "precio_unitario_usd": 120, "peso_kg": 1.5}]}, textos)
    assert not isinstance(ok, str) and len(ok[0]) == 2
    malo = validar_productos({"productos": [
        {"producto": "polos", "precio_unitario_usd": 20, "cantidad": 2, "peso_kg": 1},
        {"producto": "zapatillas", "precio_unitario_usd": 150, "peso_kg": 1.5}]}, textos)
    assert isinstance(malo, str) and malo.startswith("Producto 2")


def test_mensaje_de_varios_productos():
    msg = E.formatear_mensaje_whatsapp(E.calcular_pedido([POLOS, NIKE]))
    assert "*1. Polos (Amazon)* · 2 × USD 20.00 + TAX USD 2.80 (estimado 7 %) · 1 kg" in msg
    assert "• *Desaduanaje:* USD 9.00" in msg and "💰 *TOTAL ESTIMADO:* USD 202.70" in msg
    assert "Estimado: el TAX de Polos, Zapatillas Nike (7 %)." in msg


def test_herramienta_con_varios_productos_cotiza_y_resume(entorno):  # noqa: F811
    texto = "2 polos de amazon de 20 dólares cada uno, 1 kg, y unas zapatillas nike de 120 dólares de 1.5 kg"
    entorno("PE.ped1", texto, [_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "Polos", "tienda": "Amazon", "precio_unitario_usd": 20, "cantidad": 2, "peso_kg": 1},
        {"producto": "Zapatillas Nike", "tienda": None, "precio_unitario_usd": 120, "peso_kg": 1.5}]})])])
    assert "USD 202.70" in texto_bot_registrado("PE.ped1")
    chat = main.obtener_chat("PE.ped1")
    resumen = main.construir_resumen("PE.ped1", "asesor")
    assert "Polos (Amazon) 2 × USD 20.00, 1 kg" in resumen and "Zapatillas Nike 1 × USD 120.00, 1.5 kg" in resumen
    assert chat["bot_activo"] == 1


def test_maximo_por_dni_se_revisa_por_producto(entorno):  # noqa: F811
    texto = "10 polos de 15 dólares cada uno, 2 kg, y 2 pares de zapatillas de 60 dólares cada par, 1.5 kg"
    entorno("PE.ped2", texto, [_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "polos", "precio_unitario_usd": 15, "cantidad": 10, "peso_kg": 2},
        {"producto": "zapatillas", "precio_unitario_usd": 60, "cantidad": 2, "peso_kg": 1.5}]})])])
    # 10 polos no tienen máximo y 2 pares de zapatillas están bajo el máximo de 5: se cotiza
    assert main.obtener_chat("PE.ped2")["bot_activo"] == 1


def test_tributos_desde_usd_200_inclusive():
    """Confirmado por el usuario (15/11): se cobran tributos si producto + TAX es mayor o igual a USD 200."""
    from pricing_engine import GlobexPricingEngine as M
    justo = M.calcular_pedido([{"producto": "x", "precio_unitario": 200, "cantidad": 1, "peso_kg": 1, "tax": 0}])
    assert justo["aplica_impuesto"] and justo["tributos_aprox"] == 48.0
    debajo = M.calcular_pedido([{"producto": "x", "precio_unitario": 199.99, "cantidad": 1, "peso_kg": 1, "tax": 0}])
    assert not debajo["aplica_impuesto"] and debajo["tributos_aprox"] == 0.0
