"""Borrador estructurado del pedido: datos parciales, estados del TAX y su uso en el resumen y la API."""

import borrador
from tests.test_eval_api import KEY, api  # noqa: F401  (fixture)
from tests.test_tool_calling import _respuesta, _tool_call
from validaciones import validar_datos_parciales


def test_datos_parciales_se_anclan_al_texto():
    textos = ["Quiero traer una laptop de 650 dólares de Amazon"]
    items, total = validar_datos_parciales(
        {"productos": [{"producto": "laptop", "tienda": "Amazon", "precio_unitario_usd": 650}]}, textos)
    assert items[0]["precio_unitario"] == 650 and items[0]["peso_kg"] is None and total is None
    # un precio o un peso inventado se rechaza igual que al cotizar
    assert isinstance(validar_datos_parciales({"productos": [{"precio_unitario_usd": 700}]}, textos), str)
    assert isinstance(validar_datos_parciales({"productos": [{"peso_kg": 2}]}, textos), str)


def test_estados_del_tax():
    assert borrador.estado_tax({}, None) == borrador.TAX_DESCONOCIDO
    assert borrador.estado_tax({"tax_tienda_usd": 3}, 3.0) == borrador.TAX_CONFIRMADO
    assert borrador.estado_tax({"tax_tienda_usd": 0}, 0.0) == borrador.TAX_CERO
    assert borrador.estado_tax({"sin_tax": True}, 0.0) == borrador.TAX_INCLUIDO


def test_pendientes_por_linea():
    datos = borrador.construir(
        [{"producto": "laptop", "precio_unitario": 650, "cantidad": 1, "peso_kg": None, "tax": None},
         {"producto": None, "precio_unitario": None, "cantidad": 1, "peso_kg": 1.0, "tax": None}],
        [{}, {}], None)
    assert datos["pendientes"] == ["laptop: peso en kg", "P2: nombre del producto", "P2: precio en USD"]
    assert [l["id"] for l in datos["lineas"]] == ["P1", "P2"]
    # con un peso total del pedido, ya no falta el peso de cada producto
    assert borrador.construir([{"producto": "a", "precio_unitario": 5, "cantidad": 1, "peso_kg": None,
                                "tax": None}], [{}], 2.0)["pendientes"] == []


def test_api_devuelve_el_borrador_antes_de_cotizar(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([
        _respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
            {"producto": "Laptop Lenovo", "tienda": "Amazon", "precio_unitario_usd": 650, "peso_kg": None}]})]),
        _respuesta(content="¿Cuánto pesa aproximadamente en kg? 📦"),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B1", "id": "REC-B1", "pregunta": "Quiero traer una laptop Lenovo de Amazon de 650 dólares"}).json()
    datos = r["datos_recopilados"]
    assert datos["productos"][0]["precio"] == 650.0 and datos["productos"][0]["peso"] is None
    assert datos["productos"][0]["tax_estado"] == "desconocido"
    assert datos["pendientes"] == ["Laptop Lenovo: peso en kg"] and datos["cotizacion_aceptada"] is False
    texto = r["resumen_caso"]["texto"]
    assert "*Pedido (sin cotizar):* Laptop Lenovo (Amazon) USD 650.00" in texto
    assert "Pedir Laptop Lenovo: peso en kg" in texto and r["resumen_caso"]["campos_faltantes"] == []


def test_cotizacion_rechazada_guarda_lo_valido(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([
        _respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
            {"producto": "zapatillas", "precio_unitario_usd": 120, "peso_kg": None}]})]),
        _respuesta(content="¿Cuánto pesa aproximadamente en kg? 📦"),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B2", "id": "REC-B2", "pregunta": "Unas zapatillas de 120 dólares"}).json()
    datos = r["datos_recopilados"]
    assert datos["productos"][0]["precio"] == 120.0 and datos["cotizacion_aceptada"] is False
    assert "peso" in datos["error_cotizacion"]


def test_cotizacion_aceptada_guarda_total_y_estado_del_tax(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "audífonos", "precio_unitario_usd": 80, "peso_kg": 0.5, "sin_tax": True}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B3", "id": "REC-B3", "pregunta": "Unos audífonos de 80 dólares, ya incluye el tax, pesa 0.5 kg"}).json()
    producto = r["datos_recopilados"]["productos"][0]
    assert producto["tax_estado"] == "incluido_sin_desglose" and producto["sin_tax"] is True
    assert producto["tipo_precio"] == "final" and r["datos_recopilados"]["cotizacion_aceptada"]
    assert "(TAX incluido)" in r["resumen_caso"]["texto"]


def test_producto_de_un_mensaje_anterior_se_revisa_antes_de_cotizar(api):  # noqa: F811
    """El guardrail mira el mensaje actual; al cotizar se revisa de nuevo cada producto del pedido."""
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "biberón", "precio_unitario_usd": 30, "peso_kg": 0.4}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B4", "id": "MER-B4", "pregunta": "Cuesta 30 dólares y pesa 0.4 kg"}).json()
    assert r["tipo_respuesta"] == "guardrail" and not r["cotizacion"]["emitida"]
    assert "no transporta" in r["respuesta_bot"]
    assert r["datos_recopilados"]["cotizacion_aceptada"] is False


def test_ropa_usada_no_se_cotiza_en_el_mensaje_siguiente(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "ropa", "precio_unitario_usd": 40, "peso_kg": 1}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B5", "id": "MER-B5",
        "mensajes": ["Quiero traer ropa usada", "Cuesta 40 dólares y pesa 1 kg"]}).json()
    assert [t["tipo_respuesta"] for t in r["turnos"]] == ["guardrail", "guardrail"]
    assert not r["cotizacion"]["emitida"] and "no puedo cotizar productos usados" in r["respuesta_bot"]
    assert r["registros_acciones"]["bot_pausado"] is False  # informa, no deriva


def test_si_aclara_que_es_nueva_se_cotiza(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "ropa", "precio_unitario_usd": 40, "peso_kg": 1}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B6", "id": "MER-B6",
        "mensajes": ["Quiero traer ropa usada", "Perdón, es nueva: cuesta 40 dólares y pesa 1 kg"]}).json()
    assert r["turnos"][1]["tipo_respuesta"] == "cotizacion" and r["cotizacion"]["emitida"]


def test_otro_producto_despues_de_ropa_usada_se_cotiza(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "laptop", "precio_unitario_usd": 650, "peso_kg": 2.5}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B7", "id": "MER-B7",
        "mensajes": ["Quiero traer ropa usada", "Entonces una laptop de 650 dólares, 2.5 kg"]}).json()
    assert r["cotizacion"]["emitida"]


def test_perfumes_dentro_del_maximo_se_cotizan_y_si_se_pasan_derivan(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "perfumes", "precio_unitario_usd": 50, "cantidad": 3, "peso_kg": 1}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B8", "id": "MER-B8", "pregunta": "3 perfumes de 50 dólares cada uno, pesan 1 kg"}).json()
    assert r["cotizacion"]["emitida"] and not r["registros_acciones"]["bot_pausado"]
    con_llm([_respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": [
        {"producto": "perfumes", "precio_unitario_usd": 50, "cantidad": 5, "peso_kg": 1.5}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "B8", "id": "MER-B9", "pregunta": "5 perfumes de 50 dólares cada uno, pesan 1.5 kg"}).json()
    assert "máximo por DNI es de 4 unidades de perfumes" in r["respuesta_bot"]
    assert r["registros_acciones"]["bot_pausado"] and not r["cotizacion"]["emitida"]


def test_maximo_de_shampoo_es_por_cotizacion():
    from guardrails import limite_por_dni_excedido
    assert "máximo por cotización es de 2" in limite_por_dni_excedido(["shampoo"], 3)["mensaje"]


def test_direccion_miami_segun_el_flyer():
    from knowledge_base import KB_GLOBEX
    texto = KB_GLOBEX["direccion_miami"]["contenido"]
    assert "GX / tu nombre y apellido" in texto and "Suite 101" in texto and "33122" in texto
    assert "GX-XXXX" not in texto and "asignará" not in texto
