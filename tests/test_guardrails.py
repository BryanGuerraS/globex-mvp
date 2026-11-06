"""Guardrail de mercancía: palabras completas, sin falsos positivos por pedazos de palabra."""

import pytest

from guardrails import verificar_mercancia_restringida as verificar


@pytest.mark.parametrize("texto, tipo", [
    ("Quiero traer 3 perfumes por $150", "digemid"),
    ("unos COSMETICOS de Sephora", "digemid"),  # sin tildes y en mayúsculas
    ("una crema hidratante", "digemid"),
    ("medicamentos para la gripe", "digemid"),  # plural
    ("proteína whey de 2 kg", "digemid"),
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
])
def test_no_hay_falsos_positivos(texto):
    assert verificar(texto) is None
