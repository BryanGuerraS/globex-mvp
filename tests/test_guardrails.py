"""Guardrail de mercancía: palabras completas, sin falsos positivos por pedazos de palabra."""

import pytest

from guardrails import verificar_mercancia_restringida as verificar


@pytest.mark.parametrize("texto, tipo", [
    ("¿Cuántos perfumes puedo traer?", "limite_dni"),  # solo si pregunta por los máximos
    ("¿Cuál es el límite de COSMETICOS?", "limite_dni"),  # sin tildes y en mayúsculas
    ("medicamentos para la gripe", "receta"),  # plural
    ("proteína whey de 2 kg", "receta"),
    ("unos chupones y biberones para mi bebé", "prohibido"),
    ("pegamento de pestañas de 15 dólares", "prohibido"),
    ("un TV box de 60 dólares", "no_admitido"),
    ("artículos médicos para mi clínica", "no_admitido"),
    ("ropa usada de 100 dólares", "solo_nuevos"),
    ("repuestos de auto usados", "solo_nuevos"),
    ("juguetes de segunda mano", "solo_nuevos"),
    ("perfume y un vape", "prohibido"),  # lo prohibido gana a lo que se deriva
    ("Quiero importar unos vapes", "prohibido"),
    ("un vapeador y 5 pods", "prohibido"),
    ("municiones para airsoft", "prohibido"),
    ("un spray de pimienta", "prohibido"),
    ("un powerbank Anker", "baterias"),
    ("baterías de litio sueltas", "baterias"),
])
def test_detecta_mercancia(texto, tipo):
    r = verificar(texto)
    assert r is not None and r["tipo"] == tipo


@pytest.mark.parametrize("texto", [
    "¿Podrías cotizarme una laptop de 500 dólares, 2 kg?",  # "pod" dentro de "podrías"
    "Un iPod de 150 dólares",
    "Quiero un armario de 200 dólares",  # "arma" dentro de "armario"
    "Una mochila para la farmacia",  # "arma" dentro de "farmacia"
    "Una chaqueta con cremallera de 80 usd",  # "crema" dentro de "cremallera"
    "Zapatillas Nike de 120 dólares, 1 kg",
    "Un polo de algodón, ¿puedes ayudarme?",
    "Ropa nueva de Zara, 120 dólares",
    "Un juguete Lego nuevo de 80 dólares",
    "Unas botas de 90 dólares",
    # 15/11: perfumes, maquillaje y cremas se cotizan dentro del máximo (se revisa al cotizar)
    "Quiero traer 3 perfumes por $150",
    "unos COSMETICOS de Sephora",
    "una crema hidratante",
    "un sérum de The Ordinary",
])
def test_no_hay_falsos_positivos(texto):
    assert verificar(texto) is None


from guardrails import limite_por_dni_excedido as limite  # noqa: E402


@pytest.mark.parametrize("texto, cantidad, excede", [
    ("6 pares de zapatillas de 50 dólares", 6, True),
    ("5 pares de zapatillas de 50 dólares", 5, False),
    ("5 juguetes de 20 dólares", 5, True),
    ("3 shampoos de 10 dólares", 3, True),
    ("10 polos de 15 dólares", 10, False),  # la ropa nueva no tiene máximo en la lista
])
def test_limite_por_dni(texto, cantidad, excede):
    assert (limite([texto], cantidad) is not None) is excede


def test_maximo_por_dni_corto_y_detalle_solo_si_lo_pide():
    assert verificar("Quiero traer perfumes de Sephora") is None  # se cotiza
    detalle = verificar("¿Cuántos perfumes puedo traer?")["mensaje"]
    assert "• Perfumes: 4" in detalle and "• Cremas: 3" in detalle
    assert "The Ordinary" not in detalle and "asesor" not in detalle


def test_mensaje_de_prohibido_menciona_semillas_y_sprays():
    mensaje = verificar("unas semillas de tomate")["mensaje"]
    assert "semillas" in mensaje and "sprays" in mensaje


# ---- Guía de criterios (15/11): límites como datos, figuras de colección y regla retirada ----

def test_limites_con_unidad_y_ambito():
    from guardrails import LIMITES_POR_DNI
    por_nombre = {l["nombre"]: l for l in LIMITES_POR_DNI}
    assert por_nombre["calzado"]["ambito"] == "consignatario" and por_nombre["calzado"]["unidad"] == "pares"
    assert por_nombre["shampoo y productos para el cabello"]["ambito"] == "cotizacion"
    assert por_nombre["cremas"]["maximo"] == 3  # la marca no sube el máximo de la categoría
    assert "cotización" in limite(["shampoo"], 3)["detalle"]


def test_figuras_de_coleccion_pueden_pasar_de_cuatro():
    assert limite(["juguetes"], 5) is not None
    assert limite(["figuras de colección (juguetes)"], 6) is None


def test_sin_maximo_conjunto_de_cuatro_restringidos():
    detalle = verificar("¿Cuántos perfumes puedo traer como máximo?")["mensaje"]
    assert "Perfumes: 4" in detalle and "guía" not in detalle and "en total" not in detalle


@pytest.mark.parametrize("texto, tipo", [
    ("Encontré un revólver real en una tienda de USA", "prohibido"),
    ("El artículo está descrito como dispositivo médico y tengo receta", "no_admitido"),
    ("Son dos chaquetas que ya usé, pero están impecables", "solo_nuevos"),
    ("El repuesto de mi auto fue retirado de otro vehículo y es usado", "solo_nuevos"),
])
def test_banco_desarrollo_palabras_nuevas(texto, tipo):
    assert verificar(texto)["tipo"] == tipo


@pytest.mark.parametrize("texto", ["Quiero una pistola de agua", "Quiero traer una camisa nueva",
                                   "Una casaca nueva de 80 dólares, no usada"])
def test_sin_falsos_positivos_nuevos(texto):
    assert verificar(texto) is None
