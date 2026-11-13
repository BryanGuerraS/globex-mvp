"""Guardrail de mercancía: palabras completas, sin falsos positivos por pedazos de palabra."""

import pytest

from guardrails import verificar_mercancia_restringida as verificar


@pytest.mark.parametrize("texto, tipo", [
    ("Quiero traer 3 perfumes por $150", "limite_dni"),
    ("unos COSMETICOS de Sephora", "limite_dni"),  # sin tildes y en mayúsculas
    ("una crema hidratante", "limite_dni"),
    ("un sérum de The Ordinary", "limite_dni"),
    ("medicamentos para la gripe", "receta"),  # plural
    ("proteína whey de 2 kg", "receta"),
    ("unos chupones y biberones para mi bebé", "prohibido"),
    ("pegamento de pestañas de 15 dólares", "prohibido"),
    ("un TV box de 60 dólares", "restringido"),
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
    corto = verificar("Quiero traer perfumes de Sephora")["mensaje"]
    assert "máximo por DNI" in corto and "Perfumes: 4" not in corto
    detalle = verificar("¿Cuántos perfumes puedo traer?")["mensaje"]
    assert "• Perfumes: 4" in detalle and "• Cremas: 3" in detalle


def test_mensaje_de_prohibido_menciona_semillas_y_sprays():
    mensaje = verificar("unas semillas de tomate")["mensaje"]
    assert "semillas" in mensaje and "sprays" in mensaje
