"""Conversor del banco de pruebas del equipo al formato de evaluar.py (con bloques sintéticos)."""

import json

import pytest

from evaluacion import convertir_banco as cb
from evaluacion import evaluar


def _bloque(cid, resultado, accion, actual, previos="[]", valor="", peso="", estado_ref="Listo",
            procedencia="Real", origen=None):
    linea_origen = f"Caso real de origen: {origen}\n" if origen else ""
    return (
        f"INICIO_CASO {cid}\nProcedencia: {procedencia}\nEstado de referencia: {estado_ref}\n"
        f"Categoría: PRUEBA\n{linea_origen}\nENTRADA DESTINADA AL CHATBOT\n"
        'Estado inicial: {"control":"bot_autorizado"}\n'
        f"Mensajes anteriores del usuario: {previos}\nINICIO_MENSAJE_ACTUAL\n{actual}\nFIN_MENSAJE_ACTUAL\n\n"
        f"REFERENCIA EXCLUSIVA DEL EVALUADOR\nAcción esperada: {accion}\nConducta esperada: x\n"
        f"Resultado Globix: {resultado}\nValor USD: {valor}\nPeso kg: {peso}\nDuda: no\nFIN_CASO {cid}\n\n"
    )


BANCO = (
    _bloque("R1", "cotiza", "Emitir cotización preliminar", "Zapatillas de USD 75 y 500 g",
            previos='[{"texto":"Hola"}]', valor="75", peso="0.5")
    + _bloque("R1-V1", "restringido", "Orientar o derivar", "perfumes arabes", procedencia="Variante", origen="R1")
    + _bloque("R2", "deriva", "Derivar", "Quiero un asesor")
    + _bloque("R3", "faq", "Responder información", "¿Dónde queda su almacén?", estado_ref="Referencia por validar")
)


def test_lee_entrada_y_referencia():
    casos = cb.leer_banco(BANCO)
    assert [c["id"] for c in casos] == ["R1", "R1-V1", "R2", "R3"]
    assert casos[0]["mensajes"] == ["Hola", "Zapatillas de USD 75 y 500 g"]  # antecedentes + mensaje actual
    assert (casos[0]["valor"], casos[0]["peso"]) == (75.0, 0.5)
    assert casos[1]["origen"] == "R1"


def test_traduce_etiquetas_a_verificaciones():
    c = {x["id"]: cb.a_caso_evaluar(x) for x in cb.leer_banco(BANCO)}
    assert c["R1"]["esperado"] == {"tipo_final": ["cotizacion"], "cotizacion": {"valor": 75.0, "peso": 0.5},
                                   "cotiza": True, "deriva": False}
    assert "deriva" not in c["R1-V1"]["esperado"]  # "Orientar o derivar": ambas válidas
    assert c["R1-V1"]["categoria"] == "guardrail" and c["R1-V1"]["banco"]["grupo"] == "R1"
    assert c["R2"]["esperado"]["deriva"] is True
    # La referencia del evaluador nunca llega al bot: solo los mensajes
    assert all("Conducta" not in m and "Resultado" not in m for x in c.values() for m in x["mensajes"])


def test_separa_pendientes_y_evaluar_los_acepta(tmp_path):
    ruta = tmp_path / "banco.txt"
    ruta.write_text(BANCO, encoding="utf-8")
    rutas = cb.convertir(str(ruta))
    listos = json.loads(open(rutas["casos_reservados.json"], encoding="utf-8").read())["casos"]
    pendientes = json.loads(open(rutas["casos_reservados_pendientes.json"], encoding="utf-8").read())["casos"]
    assert [c["id"] for c in listos] == ["R1", "R1-V1", "R2"] and [c["id"] for c in pendientes] == ["R3"]
    # Una corrida simulada se verifica con las funciones de evaluar.py
    corrida = {"turnos": [{"cliente": "Zapatillas", "tipo_respuesta": "cotizacion", "respuestas": ["ok"],
                           "herramientas": [{"nombre": "calcular_cotizacion",
                                             "argumentos": json.dumps({"valor_producto_usd": 75, "peso_kg": 0.5}),
                                             "resultado": {"cotizacion_emitida": True}}]}],
               "bot_activo_final": 1}
    assert all(ch["ok"] for ch in evaluar.evaluar_corrida(listos[0], corrida))


def test_etiqueta_desconocida_falla():
    with pytest.raises(ValueError):
        cb.a_caso_evaluar({**cb.leer_banco(BANCO)[0], "resultado": "inventada"})
