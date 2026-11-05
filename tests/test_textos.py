"""Textos aprobados el 05/11 (documento 'Textos de Globix · revisión')."""

import pytest

import guardrails
import main


def _emojis(texto):
    # Variaciones (U+FE0F) y unión (U+200D) no cuentan como emoji aparte
    return sum(1 for c in texto if ord(c) >= 0x2600 and c not in "️‍")


TEXTOS_FIJOS = {
    "bienvenida": main.texto_bienvenida(None, True),
    "menu_repetido": main.texto_bienvenida(None, False),
    "derivacion": main.texto_derivacion("Ana"),
    "pregunta_nombre": main.PREGUNTA_NOMBRE,
    "fuera_de_alcance": main.TEXTO_FUERA_DE_ALCANCE,
    "error": main.RESPUESTA_ERROR,
    "recuperacion": main.TEXTO_RECUPERACION,
    "leyenda_proforma": main.LEYENDA_PROFORMA,
    "recordatorio": main.texto_recordatorio("Ana Pérez", 836.33),
    **{f"guardrail_{k}": v["mensaje"] for k, v in guardrails.RESTRICCIONES_ADUANA.items()},
}


@pytest.mark.parametrize("nombre, texto", TEXTOS_FIJOS.items())
def test_como_maximo_un_emoji(nombre, texto):
    assert _emojis(texto) <= 1, nombre


def test_bienvenida_sin_nombre():
    assert main.texto_bienvenida("Ana", True).startswith("¡Hola! 👋")


def test_recordatorio_no_ofrece_casillero_y_usa_usd():
    t = main.texto_recordatorio(None, 836.33)
    assert t.startswith("¡Hola! 👋") and "USD 836.33" in t
    assert "casillero" not in t.lower()
    assert main.texto_recordatorio("Ana Pérez", 10).startswith("¡Hola, Ana! 👋")


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("¡Listo! Un asesor te escribirá. 🙌", "¡Listo! Un asesor te escribirá.\n\n" + main.PREGUNTA_NOMBRE),
        ("📦 Recibí tu consulta.", "📦 Recibí tu consulta.\n\n" + main.PREGUNTA_NOMBRE.replace(" 😊", "")),
        ("Como tu compra supera los USD 1,200.", "Como tu compra supera los USD 1,200.\n\n" + main.PREGUNTA_NOMBRE),
    ],
)
def test_pedido_de_nombre_deja_un_solo_emoji(texto, esperado):
    chat = f"PE.txt{abs(hash(texto)) % 10000}"
    main.registrar_mensaje_entrante(chat, "Cliente", "hola")
    resultado = main.con_pedido_de_nombre(texto, chat)
    assert resultado == esperado and _emojis(resultado) <= 1


def test_no_pide_nombre_dos_veces():
    main.registrar_mensaje_entrante("PE.txt-2", "Cliente", "hola")
    main.con_pedido_de_nombre("¡Listo! 🙌", "PE.txt-2")
    assert main.con_pedido_de_nombre("¡Listo! 🙌", "PE.txt-2") == "¡Listo! 🙌"
