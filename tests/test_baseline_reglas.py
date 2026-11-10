"""Baseline sin LLM (evaluacion/baseline_reglas.py)."""

import asyncio

import pytest

import main
from evaluacion import baseline_reglas as br


@pytest.mark.parametrize("texto, esperado", [
    ("Quiero hablar con un asesor", "derivar_a_asesor"),
    ("¿Dónde está mi paquete? tracking 123", "clasificar_como_seguimiento"),
    ("Viajo con maleta, ¿puedo traer cosas?", "clasificar_como_viajero"),
    ("Una laptop de USD 650 que pesa 2.5 kg", "calcular_cotizacion"),
    ("Un iPhone de 900 dólares", "consultar_peso_producto"),
    ("¿Cuál es la dirección del almacén?", "consultar_faq_comercial"),
    ("Quiero cotizar", "texto"),
    ("Hola", "mostrar_menu"),
    ("Es para uso personal", "mostrar_menu"),  # "personal" no es "persona"
])
def test_decide_por_reglas(texto, esperado):
    assert br.decidir([texto])[0] == esperado


def test_extrae_valor_y_peso_con_unidades():
    assert br.extraer_valor_y_peso("zapatillas de USD 75 y 500 g") == (75.0, 0.5)
    assert br.extraer_valor_y_peso("$120, 3 libras") == (120.0, 1.361)
    assert br.decidir(["laptop USD 650", "2.5 kg"])[1]["peso_kg"] == 2.5  # completa con el mensaje anterior


def test_cotiza_con_el_flujo_real_sin_llm(monkeypatch, bloquear_meta):
    monkeypatch.setattr(main, "client", br.ClienteReglas())
    main.registrar_mensaje_entrante("BASE-1", "Cliente", "Una laptop de USD 650 que pesa 2.5 kg")
    asyncio.run(main.procesar_mensaje_consolidado("BASE-1", "Cliente", "Una laptop de USD 650 que pesa 2.5 kg"))
    assert main.obtener_chat("BASE-1")["cotizacion_total"] == pytest.approx(836.33)
