"""Los 60 casos sintéticos de verificación del motor (evaluacion/casos_motor.json)."""

import pytest

from evaluacion.verificar_motor import cargar_casos, verificar_caso

# Fallos conocidos, pendientes de confirmar con el equipo antes de tocar el motor.
# (M06, redondeo de 9.045, se corrigió el 05/11 al pasar el motor a Decimal.)
CONOCIDOS: dict = {}

CASOS = cargar_casos()


def test_son_60_casos_en_10_categorias():
    assert len(CASOS) == 60
    assert len({c["id"] for c in CASOS}) == 60
    assert len({c["categoria"] for c in CASOS}) == 10


def test_el_json_esta_al_dia_con_el_oraculo():
    from evaluacion.generar_casos_motor import generar
    assert generar()["casos"] == CASOS


@pytest.mark.parametrize(
    "caso",
    [pytest.param(c, id=c["id"], marks=[pytest.mark.xfail(reason=CONOCIDOS[c["id"]], strict=True)]
                  if c["id"] in CONOCIDOS else []) for c in CASOS],
)
def test_caso_motor(caso):
    resultado = verificar_caso(caso)
    assert resultado["ok"], resultado["diferencias"]
