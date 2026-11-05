"""Pruebas del bucle de tool calling con un LLM simulado (sin Groq ni Meta)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import main
from tests.utilidades import mensajes_enviados


def _tool_call(id_, nombre, args):
    return SimpleNamespace(
        id=id_,
        type="function",
        function=SimpleNamespace(
            name=nombre, arguments=args if isinstance(args, str) else json.dumps(args)
        ),
    )


def _respuesta(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class LLMFalso:
    """Devuelve respuestas predefinidas y guarda los historiales que recibió."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def create(self, **kwargs):
        self.llamadas.append([dict(m) for m in kwargs["messages"]])
        if not self.respuestas:
            raise AssertionError("El LLM se llamó más veces de lo esperado")
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def entorno(monkeypatch, bloquear_meta):
    main.sessions.clear()

    def correr(chat_id, texto, respuestas):
        # Como en el webhook real: el chat existe en la BD antes de procesarse.
        main.registrar_mensaje_entrante(chat_id, "Cliente", texto)
        llm = LLMFalso(respuestas)
        monkeypatch.setattr(
            main, "client", SimpleNamespace(chat=SimpleNamespace(completions=llm))
        )
        asyncio.run(main.procesar_mensaje_consolidado(chat_id, "Cliente", texto))
        return llm, mensajes_enviados(bloquear_meta)[-1]

    return correr


def _historial_valido(history):
    """Cada tool_call del asistente debe tener su mensaje 'tool' de respuesta."""
    pendientes = set()
    for m in history:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            assert not pendientes, "tool_calls sin respuesta antes de otro turno"
            pendientes = {tc["id"] for tc in m["tool_calls"]}
        elif m.get("role") == "tool":
            pendientes.discard(m["tool_call_id"])
    assert not pendientes


def test_cotizacion_directa(entorno):
    llm, enviado = entorno(
        "chat_cot",
        "laptop de 1000 dólares que pesa 2.5 kg",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 1000, "peso_kg": 2.5})])],
    )
    assert "1,265.85" in enviado
    assert len(llm.llamadas) == 1
    _historial_valido(main.sessions["chat_cot"]["history"])


def test_procesa_todas_las_tool_calls(entorno):
    """Peso de catálogo + FAQ en el mismo mensaje del LLM, luego cotización."""
    llm, enviado = entorno(
        "chat_multi",
        "iphone de 1100 dólares, ¿cuánto demora?",
        [
            _respuesta(
                tool_calls=[
                    _tool_call("t1", "consultar_peso_producto", {"nombre_producto": "iphone"}),
                    _tool_call("t2", "consultar_faq_comercial", {"tema": "plazos_entrega"}),
                ]
            ),
        ],
    )
    # La FAQ es respuesta final; la consulta de peso también quedó registrada.
    history = main.sessions["chat_multi"]["history"]
    tools = [m for m in history if m.get("role") == "tool"]
    assert {m["tool_call_id"] for m in tools} == {"t1", "t2"}
    _historial_valido(history)


def test_peso_de_catalogo_y_luego_cotizacion(entorno):
    peso_catalogo = main.buscar_peso_producto("iphone")["peso_kg"]
    llm, enviado = entorno(
        "chat_rag",
        "quiero cotizar un iphone de 1100 dólares",
        [
            _respuesta(tool_calls=[_tool_call("t1", "consultar_peso_producto", {"nombre_producto": "iphone"})]),
            _respuesta(tool_calls=[_tool_call("t2", "calcular_cotizacion", {"valor_producto_usd": 1100, "peso_kg": peso_catalogo})]),
        ],
    )
    assert "peso estimado con caja" in enviado
    assert "COTIZACIÓN ESTIMADA" in enviado
    _historial_valido(main.sessions["chat_rag"]["history"])


def test_valor_inventado_no_cotiza_y_el_llm_repregunta(entorno):
    llm, enviado = entorno(
        "chat_inv",
        "quiero traer una laptop que pesa 2 kg",
        [
            _respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 900, "peso_kg": 2})]),
            _respuesta(content="¿Cuál es el precio de la laptop en USD?"),
        ],
    )
    assert enviado == "¿Cuál es el precio de la laptop en USD?"
    # El rechazo se le devolvió al LLM como resultado de la herramienta.
    tool_msg = [m for m in llm.llamadas[1] if m.get("role") == "tool"][0]
    assert "error" in json.loads(tool_msg["content"])
    _historial_valido(main.sessions["chat_inv"]["history"])


def test_herramienta_desconocida_no_rompe(entorno):
    llm, enviado = entorno(
        "chat_desc",
        "hola",
        [
            _respuesta(tool_calls=[_tool_call("t1", "herramienta_inventada", {})]),
            _respuesta(content="¡Hola! ¿En qué te ayudo?"),
        ],
    )
    assert enviado == "¡Hola! ¿En qué te ayudo?"
    _historial_valido(main.sessions["chat_desc"]["history"])


def test_argumentos_json_invalidos(entorno):
    llm, enviado = entorno(
        "chat_json",
        "cuesta 100 y pesa 1 kg",
        [
            _respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", "{no es json")]),
            _respuesta(content="¿Me confirmas el precio y el peso?"),
        ],
    )
    assert enviado == "¿Me confirmas el precio y el peso?"


def test_limite_de_rondas(entorno):
    bucle = [
        _respuesta(tool_calls=[_tool_call(f"t{i}", "consultar_peso_producto", {"nombre_producto": "x"})])
        for i in range(main.MAX_RONDAS_HERRAMIENTAS)
    ]
    llm, enviado = entorno("chat_bucle", "algo", bucle)
    assert len(llm.llamadas) == main.MAX_RONDAS_HERRAMIENTAS
    assert enviado == main.RESPUESTA_ERROR
    _historial_valido(main.sessions["chat_bucle"]["history"])


def test_contenido_vacio_usa_respuesta_de_respaldo(entorno):
    llm, enviado = entorno("chat_vacio", "hola", [_respuesta(content=None)])
    assert enviado == main.RESPUESTA_ERROR


def test_error_a_mitad_deja_historial_valido(entorno):
    llm, enviado = entorno(
        "chat_err",
        "iphone",
        [
            _respuesta(tool_calls=[_tool_call("t1", "consultar_peso_producto", {"nombre_producto": "iphone"})]),
            RuntimeError("Groq caído"),
        ],
    )
    assert enviado == main.RESPUESTA_ERROR
    _historial_valido(main.sessions["chat_err"]["history"])


def _estado_chat(chat_id):
    return next(c for c in main.obtener_todos_los_chats() if c["chat_id"] == chat_id)


def test_escape_lo_decide_el_llm(entorno):
    llm, enviado = entorno(
        "chat_esc",
        "quiero hablar con un asesor",
        [_respuesta(tool_calls=[_tool_call("t1", "derivar_a_asesor", {"motivo": "pide asesor"})])],
    )
    assert enviado == main.texto_derivacion(None) + "\n\n" + main.PREGUNTA_NOMBRE
    chat = _estado_chat("chat_esc")
    assert chat["estado"] == "Listo para Asesor" and chat["bot_activo"] == 0
    _historial_valido(main.sessions["chat_esc"]["history"])


def test_palabra_persona_sin_intencion_no_deriva(entorno):
    """Sin regla de palabras clave: si el LLM no deriva, el bot sigue atendiendo."""
    llm, enviado = entorno(
        "chat_pers",
        "es un regalo para una persona, ¿cómo se llama su tienda?",
        [_respuesta(content="Somos Globex Courier, ¿qué producto deseas traer?")],
    )
    assert len(llm.llamadas) == 1
    assert enviado == "Somos Globex Courier, ¿qué producto deseas traer?"


def test_herramienta_derivar_esta_disponible_para_el_llm():
    nombres = {t["function"]["name"] for t in main.TOOLS}
    assert "derivar_a_asesor" in nombres


def test_tope_1200_deriva_sin_cotizar(entorno):
    llm, enviado = entorno(
        "chat_tope",
        "una laptop de 1500 dólares que pesa 2 kg",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 1500, "peso_kg": 2})])],
    )
    assert "más de USD 1,200" in enviado
    assert "COTIZACIÓN" not in enviado
    chat = _estado_chat("chat_tope")
    assert chat["estado"] == "Listo para Asesor" and chat["bot_activo"] == 0


def test_valor_en_palabras_cotiza(entorno):
    llm, enviado = entorno(
        "chat_mil",
        "una laptop de mil dólares que pesa dos kilos",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 1000, "peso_kg": 2})])],
    )
    assert "COTIZACIÓN ESTIMADA" in enviado


def test_peso_bajo_1kg_cobra_minimo(entorno):
    llm, enviado = entorno(
        "chat_min",
        "unos audífonos de 150 dólares que pesan 300 gramos",
        [_respuesta(tool_calls=[_tool_call("t1", "calcular_cotizacion", {"valor_producto_usd": 150, "peso_kg": 0.3})])],
    )
    assert "$18.00 USD (0.3 kg, se cobra el mínimo de 1 kg)" in enviado
