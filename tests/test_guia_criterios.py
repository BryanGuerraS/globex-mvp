"""Guía de criterios (15/11): nombre en cualquier mensaje, negaciones, precio base desde total − TAX,
pedido vigente con ids estables y resumen con hechos vigentes."""

import pytest

import borrador
import main
from guardrails import verificar_mercancia_restringida as verificar
from tests.test_eval_api import KEY, api  # noqa: F401  (fixture)
from tests.test_tool_calling import _respuesta, _tool_call
from validaciones import extraer_nombre, nombre_en_frase, validar_productos


@pytest.mark.parametrize("texto, nombre", [
    ("Me llamo Ana y quiero saber cuánto demora un envío", "Ana"),
    ("Hola, soy Carla. Quiero cotizar", "Carla"),
    ("Mi nombre es Luis Pérez, quiero traer una laptop", "Luis Pérez"),
    ("quiero traer una laptop, me llamo josé", "José"),
    ("soy de Lima", None),
    ("Soy peruano y quiero importar", None),
    ("Quiero cotizar una laptop", None),
])
def test_nombre_en_cualquier_mensaje(texto, nombre):
    assert nombre_en_frase(texto) == nombre


def test_una_pregunta_no_es_un_nombre():
    assert extraer_nombre("¿Sigues ahí?") is None and extraer_nombre("Ana Pérez") == "Ana Pérez"


def test_api_guarda_el_nombre_dicho_al_inicio(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(content="¡Claro! 😊 Cuéntame qué producto quieres traer.")])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "N1", "id": "NOM-1", "pregunta": "Hola, me llamo Ana y quiero cotizar"}).json()
    assert r["datos_recopilados"]["nombre_cliente"] == "Ana"
    assert "*Cliente:* Ana" in r["resumen_caso"]["texto"]


def test_api_responde_el_nombre_pedido_al_derivar(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("d1", "derivar_a_asesor", {"motivo": "pide asesor"})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "N2", "id": "NOM-2", "mensajes": ["Quiero un asesor", "Rosa Díaz"]}).json()
    assert r["turnos"][1]["tipo_respuesta"] == "nombre" and "Gracias, Rosa" in r["turnos"][1]["respuesta_bot"]
    assert "*Cliente:* Rosa Díaz" in r["resumen_caso"]["texto"]


@pytest.mark.parametrize("texto", [
    "No es un vape, es un parlante de 40 dólares",
    "no traigo armas ni municiones, solo una mochila",
    "no quiero vitaminas, quiero una laptop",
    "Es ropa nueva, no usada",
    "repuestos que no son usados",
])
def test_mencion_negada_no_activa_el_guardrail(texto):
    assert verificar(texto) is None


@pytest.mark.parametrize("texto", ["Quiero traer un vape", "Tengo un vape, no es para vender",
                                   "quiero traer ropa usada"])
def test_mencion_afirmada_si_lo_activa(texto):
    assert verificar(texto) is not None


def test_precio_base_desde_total_menos_tax():
    textos = ["Una cafetera, pagué USD 107 en total, de eso 7 son de TAX, pesa 2 kg"]
    productos, _ = validar_productos({"productos": [
        {"producto": "cafetera", "precio_unitario_usd": 100, "tax_tienda_usd": 7, "peso_kg": 2}]}, textos)
    assert productos[0]["precio_unitario"] == 100 and productos[0]["tax"] == 7
    # sin el TAX dicho, 100 no sale del texto: se rechaza
    assert isinstance(validar_productos({"productos": [
        {"producto": "cafetera", "precio_unitario_usd": 100, "peso_kg": 2}]}, textos), str)
    datos = borrador.construir(productos, [{"tax_tienda_usd": 7}], None, textos=textos)
    assert datos["lineas"][0]["origen_precio"] == "derivado"


def test_ids_estables_al_agregar_quitar_y_corregir():
    lineas = [{"producto": "mochila"}, {"producto": "Laptop"}]
    borrador._ids_estables(lineas, [{"id": "P1", "producto": "laptop"}, {"id": "P2", "producto": "mouse"}])
    assert [l["id"] for l in lineas] == ["P3", "P1"]


def test_pedido_vigente_va_al_llm(api):  # noqa: F811
    cliente, con_llm = api
    llm = con_llm([
        _respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
            {"producto": "Laptop Lenovo", "precio_unitario_usd": 650}]})]),
        _respuesta(content="¿Algo más? 😊"),
    ])
    cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "V1", "id": "VIG-1",
        "mensajes": ["Quiero traer una laptop Lenovo de 650 dólares", "¿Y cuánto demora?"]})
    sistema = llm.llamadas[-1][0]["content"]
    assert "PEDIDO VIGENTE" in sistema and "P1: Laptop Lenovo, USD 650.00, peso pendiente" in sistema


def test_resumen_separa_cotizacion_previa_de_la_correccion(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([
        _respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
            {"producto": "zapatillas", "precio_unitario_usd": 120, "peso_kg": 1.5}]})]),
        _respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
            {"producto": "zapatillas", "precio_unitario_usd": 140, "peso_kg": 1.5}]})]),
        _respuesta(content="Entendido 😊"),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "V2", "id": "VIG-2",
        "mensajes": ["Unas zapatillas de 120 dólares, 1.5 kg", "Perdón, en realidad cuestan 140 dólares"]}).json()
    texto = r["resumen_caso"]["texto"]
    assert "*Pedido vigente (sin recotizar):* zapatillas USD 140.00, 1.5 kg" in texto
    assert "*Cotización previa:* total USD" in texto and "USD 120.00" not in texto
    assert r["datos_recopilados"]["productos"][0]["precio"] == 140.0
    assert r["datos_recopilados"]["productos"][0]["id"] == "P1"


def test_resumen_marca_peso_de_catalogo_y_tax_confirmado():
    datos = {"lineas": [{"id": "P1", "producto": "iPhone", "tienda": "", "cantidad": 1, "precio_unitario_usd": 1000,
                         "peso_kg": 0.45, "origen_peso": "catalogo", "tax": {"estado": "confirmado", "monto_usd": 70}}]}
    assert "0.45 kg (catálogo)" in borrador.describir_lineas(datos)[0]
    assert "TAX USD 70.00 dicho por el cliente" in borrador.describir_lineas(datos)[0]
    assert main.borrador is borrador


def test_precio_y_tax_aparte_no_se_restan():
    """'Una tablet de 400, el tax fue 28' es base 400 + TAX 28: 372 no se acepta."""
    textos = ["Una tablet de 400 dólares, el tax fue 28 dólares, pesa 1 kg"]
    assert isinstance(validar_productos({"productos": [
        {"producto": "tablet", "precio_unitario_usd": 372, "tax_tienda_usd": 28, "peso_kg": 1}]}, textos), str)
