"""Pruebas de alcance: temas ajenos (capa 1) y revisión de salida (capa 2)."""

import asyncio
from types import SimpleNamespace

import pytest

import main
from tests.test_tool_calling import LLMFalso, _respuesta, _tool_call
from validaciones import revisar_respuesta_libre

RESPUESTA_PYTHON = (
    "En Python puedes ordenar una lista con el método `sort()` (modifica la lista) o con la "
    "función `sorted()`. Por ejemplo:\n\n```python\nmi_lista = [3, 1, 4, 2]\nmi_lista.sort()\n```"
)


# ---------- Capa 2: revisión determinista ----------

@pytest.mark.parametrize(
    "texto, motivo",
    [
        (RESPUESTA_PYTHON, "codigo"),
        ("Usa `sorted(lista)`", "codigo"),
        ("def f():\n    return 1", "codigo"),
        ("Mira https://ejemplo.com", "enlace"),
        ("Visita www.otra-web.com", "enlace"),
        ("Hola. " * 200, "muy_larga"),
        ("El envío te sale unos $35 aproximadamente.", "monto_no_dado"),
        ("Para eso necesitas 120 dólares.", "monto_no_dado"),
    ],
)
def test_bloquea(texto, motivo):
    assert revisar_respuesta_libre(texto, ["hola"]) == motivo


@pytest.mark.parametrize(
    "texto, cliente",
    [
        ("¿Cuánto pesa aproximadamente en kg?", ["set de cuchillos de $640"]),
        ("Perfecto, tu laptop de $650. ¿Cuánto pesa en kg?", ["laptop de 650 usd"]),
        ("Entendido, un celular de mil dólares. ¿Cuánto pesa?", ["un celular de mil dólares"]),
        ("¡Hola! ¿En qué te ayudo?", ["hola"]),
        (None, []),
    ],
)
def test_permite(texto, cliente):
    assert revisar_respuesta_libre(texto, cliente) is None


# ---------- Flujo completo ----------

@pytest.fixture
def turno(monkeypatch, bloquear_meta):
    def correr(chat_id, texto, respuestas):
        main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm)))
        antes = len(bloquear_meta)
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, "Cliente", texto))
        return bloquear_meta[antes:]

    return correr


def _cuerpo_y_botones(payloads):
    (msg,) = [p for p in payloads if p.get("type") == "interactive"]
    botones = [b["reply"]["id"] for b in msg["interactive"]["action"]["buttons"]]
    return msg["interactive"]["body"]["text"], botones


def test_tema_ajeno_responde_texto_fijo_con_botones(turno):
    enviados = turno(
        "al_suma", "¿Cuánto es 2+2?",
        [_respuesta(tool_calls=[_tool_call("t1", "fuera_de_alcance", {"tema": "matemáticas"})])],
    )
    cuerpo, botones = _cuerpo_y_botones(enviados)
    assert cuerpo == main.TEXTO_FUERA_DE_ALCANCE
    assert botones == ["cotizar", "rastrear", "otras"]


def test_si_el_llm_responde_codigo_se_bloquea(turno):
    """El caso real: el LLM respondió cómo ordenar una lista en Python."""
    enviados = turno("al_py", "Cómo se ordena una lista en python?", [_respuesta(content=RESPUESTA_PYTHON)])
    cuerpo, botones = _cuerpo_y_botones(enviados)
    assert cuerpo == main.TEXTO_FUERA_DE_ALCANCE
    assert "sort" not in cuerpo
    # En la BD queda lo que se envió, no la respuesta bloqueada
    assert "sort" not in main.obtener_mensajes_chat("al_py")[-1]["texto"]


def test_precio_inventado_por_el_llm_se_bloquea(turno):
    enviados = turno("al_monto", "¿cuánto me costaría traer algo?", [_respuesta(content="Te costaría unos $45 aprox.")])
    cuerpo, _ = _cuerpo_y_botones(enviados)
    assert cuerpo == main.TEXTO_FUERA_DE_ALCANCE


def test_respuesta_normal_pasa(turno):
    enviados = turno("al_ok", "set de cuchillos de $640", [_respuesta(content="¿Cuánto pesa aproximadamente en kg?")])
    assert [p["text"]["body"] for p in enviados if p.get("type") == "text"] == ["¿Cuánto pesa aproximadamente en kg?"]


def test_prompt_define_alcance_y_pregunta_de_peso_corta():
    prompt = main.SYSTEM_PROMPT
    assert "fuera_de_alcance" in prompt
    assert 'con este texto exacto: "¿Cuánto pesa aproximadamente en kg?"' in prompt
    assert "fuera_de_alcance" in {t["function"]["name"] for t in main.TOOLS}
