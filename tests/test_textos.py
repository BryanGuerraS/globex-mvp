"""Textos aprobados el 05/11 (documento 'Textos de Globix · revisión')."""

import pytest

import guardrails
import main


_emojis = main.contar_emojis


TEXTOS_FIJOS = {
    "bienvenida": main.texto_bienvenida(None, True),
    "menu_repetido": main.texto_bienvenida(None, False),
    "derivacion": main.texto_derivacion("Ana"),
    "pregunta_nombre": main.PREGUNTA_NOMBRE,
    "fuera_de_alcance": main.TEXTO_FUERA_DE_ALCANCE,
    "error": main.RESPUESTA_ERROR,
    "recuperacion": main.TEXTO_RECUPERACION,
    "cierre_faq": main.TEXTO_CIERRE_FAQ,
    "leyenda_proforma": main.LEYENDA_PROFORMA,
    "proforma_formal": main.TEXTO_PROFORMA_FORMAL,
    "recordatorio": main.texto_recordatorio("Ana Pérez", 836.33),
    **{f"guardrail_{k}": v["mensaje"] for k, v in guardrails.RESTRICCIONES_ADUANA.items()},
}


@pytest.mark.parametrize("nombre, texto", TEXTOS_FIJOS.items())
def test_como_maximo_dos_emojis(nombre, texto):
    assert _emojis(texto) <= main.MAX_EMOJIS_POR_MENSAJE, nombre


@pytest.mark.parametrize("tema, faq", __import__("knowledge_base").KB_GLOBEX.items())
def test_faq_con_cierre_cabe_en_un_mensaje_con_maximo_dos_emojis(tema, faq):
    mensaje = faq["contenido"] + "\n\n" + main.cierre_faq_para(faq["contenido"])
    assert len(mensaje) <= main.LIMITE_CUERPO_INTERACTIVO, tema
    assert _emojis(mensaje) <= main.MAX_EMOJIS_POR_MENSAJE, tema


def test_contar_emojis():
    assert _emojis("🇵🇪 hola ⚠️ ⏱️") == 3 and _emojis("sin emojis") == 0


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


def test_hora_de_lima_aunque_el_servidor_este_en_utc():
    from datetime import datetime, timedelta, timezone
    import database

    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    diferencia = utc - database.ahora()
    assert abs(diferencia - timedelta(hours=5)) < timedelta(seconds=5)  # Perú: UTC-5 todo el año


def test_proforma_usa_formato_usd():
    from pricing_engine import GlobexPricingEngine
    texto = GlobexPricingEngine.formatear_mensaje_whatsapp(GlobexPricingEngine.calcular(650, 2.5))
    assert "USD 836.33" in texto and "US$" not in texto and "$" not in texto.replace("USD", "")
