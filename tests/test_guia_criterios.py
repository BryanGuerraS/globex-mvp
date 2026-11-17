"""Guía de criterios (15/11): nombre en cualquier mensaje, negaciones, precio base desde total − TAX,
pedido vigente con ids estables y resumen con hechos vigentes."""

import pytest

import borrador
import main
from guardrails import verificar_mercancia_restringida as verificar
from tests.test_eval_api import KEY, api  # noqa: F401  (fixture)
from tests.test_tool_calling import _respuesta, _tool_call
from validaciones import extraer_nombre, nombre_en_frase, validar_datos_parciales, validar_productos


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
    assert "*Pedido vigente (sin recotizar):* zapatillas 1 × USD 140.00, 1.5 kg" in texto
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


def test_precio_final_que_ya_incluye_un_tax_dicho_no_lo_suma_otra_vez():
    """Banco de desarrollo VCOT007: 'precio final USD 194,30 y ya incluye USD 10,80 de TAX' -> total 212.30."""
    from pricing_engine import GlobexPricingEngine
    textos = ["El precio final es USD 194,30 y ya incluye USD 10,80 de TAX confirmado. El peso con embalaje es 1 kg."]
    bruto = {"producto": "correa", "precio_unitario_usd": 194.30, "peso_kg": 1, "tax_tienda_usd": 10.80, "sin_tax": True}
    productos, _ = validar_productos({"productos": [bruto]}, textos)
    assert GlobexPricingEngine.calcular_pedido(productos)["costo_total"] == 212.30
    linea = borrador.construir(productos, [bruto], None, textos=textos)["lineas"][0]
    assert linea["tax"] == {"estado": "incluido_desglosado", "monto_usd": 10.80} and linea["tipo_precio"] == "final"


@pytest.mark.parametrize("texto", ["Descarté el TV Box y no lo compraré. ¿Una camisa nueva cumple?",
                                   "El vape ya no lo voy a traer, solo una laptop"])
def test_producto_descartado_no_activa_el_guardrail(texto):
    assert verificar(texto) is None


# ---- El total no depende de cómo el LLM pasa el TAX (banco de desarrollo, 16/11) ----
def _total(args, texto):
    from pricing_engine import GlobexPricingEngine
    v = validar_productos({"productos": [args]}, [texto])
    assert not isinstance(v, str), v
    return GlobexPricingEngine.calcular_pedido(*v)["costo_total"]


_INCLUYE = "El precio final es USD 128,40 y ya incluye USD 8,40 de TAX confirmado. El peso con embalaje es 1 kg."


@pytest.mark.parametrize("args", [
    {"precio_unitario_usd": 128.40, "peso_kg": 1, "tax_tienda_usd": 8.40},                  # monto sin sin_tax
    {"precio_unitario_usd": 128.40, "peso_kg": 1, "tax_tienda_usd": 8.40, "sin_tax": True},  # monto y sin_tax
    {"precio_unitario_usd": 128.40, "peso_kg": 1, "sin_tax": True},                          # solo sin_tax
    {"precio_unitario_usd": 120.00, "peso_kg": 1, "tax_tienda_usd": 8.40},                   # base calculada
])
def test_precio_final_con_tax_incluido_cualquier_forma(args):
    assert _total(args, _INCLUYE) == 146.40


@pytest.mark.parametrize("args, texto, total", [
    ({"precio_unitario_usd": 199.61, "peso_kg": 1, "sin_tax": True},
     "El producto cuesta USD 199,61 antes de TAX y el checkout confirma TAX de USD 0,00. Pesa 1 kg.", 217.61),
    ({"precio_unitario_usd": 185.42, "peso_kg": 2.375},
     "El checkout confirma USD 185,42 finales con TAX incluido, sin desglosar el importe del impuesto. Pesa 2,375 kg.",
     215.80),
    ({"precio_unitario_usd": 31.55, "peso_kg": 1},
     "El precio es USD 31,55 antes de TAX. No cuento con el TAX y no tengo un precio final confirmado. Pesa 1 kg.",
     51.76),
    ({"precio_unitario_usd": 400, "peso_kg": 1, "tax_tienda_usd": 28},
     "Una tablet de 400 dólares, el tax fue 28 dólares, pesa 1 kg", 548.72),
])
def test_tax_cero_incluido_y_desconocido(args, texto, total):
    assert _total(args, texto) == pytest.approx(round(total, 2))


def test_precio_unitario_desde_un_total_por_cantidad():
    """CAN-02: '2 pares, en total 180 dólares' -> el LLM puede pasar 90 × 2 o 180 sin cantidad."""
    texto = "Son 2 pares de zapatillas, en total 180 dólares, pesan 2 kg"
    unitario = _total({"producto": "zapatillas", "precio_unitario_usd": 90, "cantidad": 2, "peso_kg": 2}, texto)
    total = _total({"producto": "zapatillas", "precio_unitario_usd": 180, "peso_kg": 2}, texto)
    assert unitario == total


def test_tax_cero_dicho_queda_como_cero_confirmado():
    """VCHAT001: 'precio final USD 17,80, con TAX confirmado de USD 0 incluido' -> tax_tienda_usd = 0."""
    textos = ["El precio final es USD 17,80, con TAX confirmado de USD 0 incluido. Pesa 0,38 kg con embalaje."]
    bruto = {"producto": "estuche", "precio_unitario_usd": 17.80, "peso_kg": 0.38, "sin_tax": True}
    productos, _ = validar_productos({"productos": [bruto]}, textos)
    datos = borrador.construir(productos, [bruto], None, textos=textos)
    api = borrador.productos_para_api(datos)[0]
    assert api["tax_estado"] == "cero_confirmado" and api["tax_tienda_usd"] == 0.0


def test_nombre_corregido_y_pendientes_reales(api):  # noqa: F811
    """VCHAT005/007: 'mi nombre correcto es…' reemplaza al anterior; el peso dado al pedir asesor ya no
    queda como pendiente; los pendientes incluyen continuar la atención y el TAX desconocido."""
    cliente, con_llm = api
    con_llm([
        _respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
            {"producto": "mochila", "tienda": "Amazon", "precio_unitario_usd": 60}]})]),
        _respuesta(tool_calls=[_tool_call("d1", "derivar_a_asesor", {"motivo": "continuar"})]),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={"corrida_id": "V3", "id": "VIG-3", "mensajes": [
        "Soy Lucía Mena. Quiero cotizar una mochila de Amazon de 60 dólares.",
        "Mi nombre correcto es Lucía Leiva. Pesa 1,2 kg con caja. Quiero que un asesor continúe."]}).json()
    texto = r["resumen_caso"]["texto"]
    assert "*Cliente:* Lucía Leiva" in texto and "Mena" not in texto.split("*Mensajes")[0]
    assert "1.2 kg" in texto and "peso en kg" not in texto
    assert "Continuar la atención que pidió el cliente" in texto and "Confirmar el TAX de mochila" in texto
    assert "*Mensajes del cliente:*" in texto and "Soy Lucía Mena" in texto


def test_usado_en_el_mensaje_aunque_el_llm_no_lo_diga():
    """VMER012: 'juguetes que mi hijo ya utilizó' no se aprueba por estar dentro del máximo."""
    from guardrails import respuesta_regla
    texto = "Quiero enviar tres juguetes que mi hijo ya utilizó. ¿Estar por debajo de cuatro hace que puedan traerlos?"
    assert "solo pueden ingresar a Perú si son *nuevos*" in respuesta_regla(texto, "juguetes, 3 unidades")
    assert verificar("La tienda vende adhesivo para colocar pestañas postizas")["tipo"] == "prohibido"


def test_monto_de_tax_incluido_se_registra_aunque_el_llm_no_lo_pase():
    """VCHAT007: 'ese total ya incluye USD 2,94 de TAX' -> tax_tienda_usd 2.94 en datos_recopilados."""
    textos = ["Cotiza una cartuchera nueva de Amazon, una unidad, USD 44,94 finales; ese total ya incluye USD 2,94 de TAX."]
    bruto = {"producto": "cartuchera", "precio_unitario_usd": 44.94, "sin_tax": True}
    items, _ = validar_datos_parciales({"productos": [bruto]}, textos)
    api = borrador.productos_para_api(borrador.construir(items, [bruto], None, textos=textos))[0]
    assert api["tax_estado"] == "incluido_desglosado" and api["tax_tienda_usd"] == 2.94 and api["sin_tax"] is True


# ---- El máximo se revisa antes de pedir precio o peso (16/11) ----
@pytest.mark.parametrize("texto, detalle", [
    ("Quiero cotizar 5 perfumes nuevos de Sephora", "5 unidades de perfumes"),
    ("Quiero traer seis pares de zapatillas", "6 pares de calzado"),
    ("Necesito cotizar tres botellas de shampoo", "3 unidades de shampoo"),
])
def test_pedido_sobre_el_maximo_se_detecta_en_el_mensaje(texto, detalle):
    assert detalle in main.limite_en_mensaje(texto)["detalle"]


@pytest.mark.parametrize("texto", ["¿5 perfumes cumplen el máximo?", "Quiero cotizar 3 perfumes",
                                   "Quiero traer 6 figuras de colección"])
def test_dentro_del_maximo_o_pregunta_no_deriva(texto):
    assert main.limite_en_mensaje(texto) is None


def test_pedido_sobre_el_maximo_no_pide_precio(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([])  # no debe llegar al LLM
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "L1", "id": "LIM-1", "pregunta": "Quiero cotizar 5 perfumes nuevos de Sephora"}).json()
    assert "máximo por DNI es de 4 unidades de perfumes" in r["respuesta_bot"]
    assert r["registros_acciones"]["bot_pausado"] and r["tipo_respuesta"] == "guardrail"


def test_registrar_con_cantidad_sobre_el_maximo_deriva(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
        {"producto": "juguetes", "cantidad": 5}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "L2", "id": "LIM-2", "pregunta": "Me cotizas cinco juguetes para mi sobrino, son 5 en total"}).json()
    assert "máximo por consignatario es de 4 unidades de juguetes" in r["respuesta_bot"]


@pytest.mark.parametrize("texto, tipo", [("Quiero traer una pistola real", "prohibido"),
                                         ("Una pistola de agua para mi hijo", None),
                                         ("Una pistola masajeadora", None)])
def test_pistola_arma_si_y_de_agua_no(texto, tipo):
    r = verificar(texto)
    assert (r["tipo"] if r else None) == tipo


# ---- Derivación (16/11): tope sin datos, reclamos, viajero ----
@pytest.mark.parametrize("texto, monto", [
    ("Voy a comprar varias cosas por unos 3500 dólares en total", 3500.0),
    ("Una laptop de USD 2.500", 2500.0),
    ("Un libro de 40 dólares", None),
    ("Mi compra es de $1,999.99", None),
])
def test_monto_sobre_el_tope(texto, monto):
    assert main.monto_sobre_tope(texto) == monto


def test_compra_sobre_el_tope_deriva_sin_pedir_datos(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([])  # no debe llegar al LLM
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "T1", "id": "TOPE-1", "pregunta": "Voy a comprar varias cosas por unos 3500 dólares en total"}).json()
    assert "supera los USD 2,000" in r["respuesta_bot"] and r["registros_acciones"]["bot_pausado"]
    assert r["registros_acciones"]["motivo_derivacion"] == "tope"


# ---- Banco final, segunda ronda (16/11): tope por suma, compra asistida explícita, cantidades por marca ----
def test_suma_de_productos_con_tax_sobre_el_tope_deriva(api):  # noqa: F811
    cliente, con_llm = api
    con_llm([_respuesta(tool_calls=[_tool_call("r1", "registrar_datos_pedido", {"productos": [
        {"precio_unitario_usd": 1200, "tax_tienda_usd": 0}, {"precio_unitario_usd": 900, "tax_tienda_usd": 0}]})])])
    r = cliente.post("/api/eval/caso", headers=KEY, json={
        "corrida_id": "T2", "id": "TOPE-2",
        "pregunta": "Dos productos en una cotización: uno de USD 1200 y otro de USD 900, con TAX de USD 0 cada uno"}).json()
    assert "supera los USD 2,000" in r["respuesta_bot"] and r["registros_acciones"]["motivo_derivacion"] == "tope"


@pytest.mark.parametrize("texto, deriva", [
    ("Quiero que Globex compre el producto por mí en la tienda de Estados Unidos.", True),
    ("¿Ustedes pueden comprar por mí en Amazon?", True),
    ("En general, ¿hacen compras por encargo?", False),
    ("Compré por Amazon y quiero cotizar", False),
])
def test_compra_asistida_explicita(texto, deriva):
    assert bool(main._COMPRA_ASISTIDA.search(texto.lower())) is deriva and (
        not deriva or not main._PREGUNTA_GENERAL.search(texto.lower()))


@pytest.mark.parametrize("texto, inicio", [
    ("Tengo dos cremas de una marca y dos de The Ordinary, ¿puedo contarlas por separado?",
     "⚠️ No: el máximo es de 3 unidades de cremas por DNI, así que 4 lo supera."),
    ("tres perfumes de una marca y uno de otra marca, ¿pasan?", "✅ Sí: traer 4 unidades de perfumes"),
])
def test_cantidades_por_marca_se_suman(texto, inicio):
    from guardrails import respuesta_regla
    assert respuesta_regla(texto).startswith(inicio)


def _derivar_con(cliente, con_llm, caso, productos, mensajes):
    con_llm([
        _respuesta(tool_calls=[_tool_call("c1", "calcular_cotizacion", {"productos": productos})]),
        _respuesta(content="Listo 😊"),
        _respuesta(tool_calls=[_tool_call("d1", "derivar_a_asesor", {"motivo": "Revisar y continuar"})]),
    ])
    r = cliente.post("/api/eval/caso", headers=KEY, json={"corrida_id": "RES", "id": caso, "mensajes": mensajes})
    return r.json()["resumen_caso"]["texto"]


def test_resumen_precio_final_aunque_el_llm_marque_sin_tax(api):  # noqa: F811
    """Precio final 64 con TAX 4 incluido: si el LLM pasa base 60 + TAX 4 con sin_tax, se muestra el final."""
    cliente, con_llm = api
    texto = _derivar_con(cliente, con_llm, "RES-1", [
        {"producto": "mochila", "tienda": "Amazon", "precio_unitario_usd": 60, "peso_kg": 0.9,
         "tax_tienda_usd": 4, "sin_tax": True}],
        ["Soy Ana Ruiz. Cotiza una mochila de Amazon, el precio FINAL es USD 64 y ya incluye USD 4 de TAX. "
         "Pesa 0,90 kg con embalaje.", "Que un asesor revise y continúe, por favor."])
    assert "1 × USD 64.00 (precio final, incluye TAX USD 4.00)" in texto and "USD 60.00" not in texto
    assert "0.9 kg con embalaje" in texto


def test_resumen_tienda_y_cantidad_pendientes(api):  # noqa: F811
    cliente, con_llm = api
    texto = _derivar_con(cliente, con_llm, "RES-2", [
        {"producto": "billetera", "tienda": "eBay", "precio_unitario_usd": 30, "peso_kg": 0.25, "sin_tax": True}],
        ["Soy Luis Paz. Billeteras de eBay a USD 30 finales cada una con TAX de USD 0 incluido, 0,25 kg. "
         "Todavía no sé cuántas voy a comprar, deja la cantidad pendiente.", "Que un asesor continúe, por favor."])
    assert "cantidad por definir × USD 30.00 c/u" in texto and "1 ×" not in texto
    assert "Confirmar la cantidad (el cliente aún no la definió)" in texto
    texto = _derivar_con(cliente, con_llm, "RES-3", [
        {"producto": "mochila", "precio_unitario_usd": 60, "peso_kg": 0.8, "sin_tax": True}],
        ["Soy Eva Sol. Una mochila de USD 60 finales con TAX de USD 0, pesa 0,8 kg. Aún no he elegido la tienda.",
         "Que un asesor continúe, por favor."])
    assert "Confirmar la tienda de EE. UU. (el cliente aún no la eligió)" in texto
