"""Pruebas del hallazgo 2: validación de argumentos que el LLM pasa al motor."""

import pytest

from validaciones import numeros_en_texto, validar_argumentos_cotizacion


def _validar(valor, peso, textos, pesos_ref=()):
    return validar_argumentos_cotizacion(
        {"valor_producto_usd": valor, "peso_kg": peso}, textos, pesos_ref
    )


# ---------- Extracción de números ----------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("cuesta 800", 800),
        ("cuesta $1,200", 1200),
        ("cuesta 1.200 dólares", 1200),
        ("pesa 2,5 kg", 2.5),
        ("pesa 2.5kg", 2.5),
        ("unos 1.5k", 1500),
    ],
)
def test_numeros_en_texto(texto, esperado):
    assert any(abs(n - esperado) < 1e-9 for n in numeros_en_texto([texto]))


# ---------- Validación de cotización ----------

def test_valido_con_datos_del_cliente():
    assert _validar(1000, 2.5, ["laptop de 1000 dólares que pesa 2.5 kg"]) == (1000.0, 2.5)


def test_datos_repartidos_en_varios_mensajes():
    assert _validar(800, 3, ["quiero traer una tv", "cuesta 800", "pesa 3 kilos"]) == (800.0, 3.0)


def test_peso_desde_catalogo():
    assert _validar(1100, 0.42, ["iphone de 1100 dólares"], pesos_ref=[0.42]) == (1100.0, 0.42)


@pytest.mark.parametrize(
    "texto, peso_kg",
    [
        ("cuesta 300 y pesa 500 g", 0.5),
        ("cuesta 300 y pesa 3 libras", 1.36),
        ("cuesta 300 y pesa 16 oz", 0.45),
    ],
)
def test_peso_en_otras_unidades(texto, peso_kg):
    assert _validar(300, peso_kg, [texto]) == (300.0, peso_kg)


def test_rechaza_valor_inventado():
    r = _validar(1500, 2, ["quiero traer una laptop que pesa 2 kg"])
    assert isinstance(r, str) and "valor" in r


def test_rechaza_peso_inventado():
    r = _validar(1000, 2.8, ["laptop de 1000 dólares"])
    assert isinstance(r, str) and "peso" in r


@pytest.mark.parametrize("valor, peso", [(0, 1), (100, 0), (-50, 1), (100, -2)])
def test_rechaza_no_positivos(valor, peso):
    assert isinstance(_validar(valor, peso, [f"{valor} {peso}"]), str)


@pytest.mark.parametrize("valor, peso", [(None, 1), ("abc", 1), (100, None), (float("nan"), 1), (float("inf"), 1)])
def test_rechaza_no_numericos(valor, peso):
    assert isinstance(_validar(valor, peso, ["100 1"]), str)


# ---------- Montos y pesos en palabras ----------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("una laptop de mil dólares", 1000),
        ("cuesta dos mil quinientos", 2500),
        ("unos 2 mil dólares", 2000),
        ("1.5 mil", 1500),
        ("trescientos cincuenta dólares", 350),
        ("ochocientos noventa y nueve", 899),
        ("cien dólares", 100),
        ("pesa medio kilo", 0.5),
        ("pesa un kilo y medio", 1.5),
        ("pesa 1 kilo y medio", 1.5),
        ("pesa kilo y medio", 1.5),
        ("un kilogramo y medio", 1.5),
        ("pesa dos kilos y medio", 2.5),
        ("pesa tres kilos", 3),
    ],
)
def test_numeros_en_palabras(texto, esperado):
    assert any(abs(n - esperado) < 1e-9 for n in numeros_en_texto([texto]))


def test_valor_en_palabras_es_valido():
    assert _validar(1000, 2, ["una laptop de mil dólares que pesa dos kilos"]) == (1000.0, 2.0)


def test_valor_en_palabras_no_inventa_otro():
    r = _validar(1500, 2, ["una laptop de mil dólares que pesa 2 kg"])
    assert isinstance(r, str) and "valor" in r


# ---------- Limpieza de notas internas del LLM ----------

from validaciones import limpiar_respuesta_llm  # noqa: E402


@pytest.mark.parametrize(
    "texto, esperado",
    [
        (
            "¿Podrías indicarme el peso aproximado en kg?\n(Esperando respuesta del cliente)",
            "¿Podrías indicarme el peso aproximado en kg?",
        ),
        ("¿Cuánto pesa en kg? (esperando respuesta)", "¿Cuánto pesa en kg?"),
        ("Perfecto. [Nota: falta el precio]\n¿Cuál es el precio en USD?", "Perfecto.\n¿Cuál es el precio en USD?"),
        # Paréntesis legítimos dentro de una frase se conservan
        ("El envío es de USD 18 (incluye trámite).", "El envío es de USD 18 (incluye trámite)."),
        ("Pesa 2 kg (aprox.) y cuesta $640", "Pesa 2 kg (aprox.) y cuesta $640"),
    ],
)
def test_limpia_notas_internas(texto, esperado):
    assert limpiar_respuesta_llm(texto) == esperado


def test_limpieza_que_deja_vacio_devuelve_none():
    assert limpiar_respuesta_llm("(Esperando respuesta del cliente)") is None
    assert limpiar_respuesta_llm(None) is None
