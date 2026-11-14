"""Genera evaluacion/casos_motor.json con un oráculo independiente en Decimal.

El oráculo NO importa el motor: reescribe las reglas desde el Excel de cotización de
Globex (hoja COURIER, adoptado el 13/11/2026) para que un error del motor no se copie
a los valores esperados.

Reglas:
  precio         = precio unitario × cantidad (celda H7 = C7*F7)
  TAX de tienda  = 7 % del precio si no se conoce; el monto dado por el cliente; 0 si no aplica
  boleta         = precio + TAX (el envío dentro de EE. UU. queda fuera del alcance)
  flete          = máx(peso, 1 kg) × USD 9
  envío          = flete + USD 9 de desaduanaje (confirmado 13/11; el USD 7 de la hoja COURIER era una prueba,
                   la hoja 'Courier Comi.' tiene USD 9)
  tributos       = 24 % de la boleta si la boleta es de USD 200 o más
  total          = boleta + envío + tributos
  tope           = boleta > USD 2 000 se deriva al asesor
Redondeo comercial a 2 decimales (ROUND_HALF_UP) en TAX, flete, envío, tributos y total.

Uso: python evaluacion/generar_casos_motor.py
"""

import json
import os
from decimal import ROUND_HALF_UP, Decimal

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "casos_motor.json")
D = Decimal


def _r(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _tax(valor: Decimal, tax) -> Decimal:
    return _r(valor * D("0.07")) if tax is None else _r(D(str(tax)))


def oraculo(valor, peso, tax=None, cantidad=1) -> dict:
    v, p = D(str(valor)) * cantidad, D(str(peso))
    boleta = v + _tax(v, tax)
    facturable = p if p >= 1 else D(1)
    flete = _r(facturable * 9)
    envio = _r(flete + 9)
    aplica = boleta >= 200
    tributos = _r(boleta * D("0.24")) if aplica else D(0)
    return {
        "tax_tienda": float(_tax(v, tax)),
        "boleta": float(boleta),
        "peso_facturable_kg": float(facturable),
        "costo_flete": float(flete),
        "costo_envio": float(envio),
        "tributos_aprox": float(tributos),
        "costo_total": float(_r(boleta + envio + tributos)),
        "aplica_impuesto": aplica,
        "requiere_asesor": boleta > 2000,
    }


def oraculo_pedido(items, peso_total=None) -> dict:
    """Pedido de varios productos (reglas del 14/11): una guía, flete sobre el peso total,
    un solo desaduanaje y tributos sobre la suma de los precios totales (producto + TAX)."""
    boleta = D(0)
    for precio, cantidad, _, tax in items:
        v = D(str(precio)) * cantidad
        boleta += v + _tax(v, tax)
    p = D(str(peso_total)) if peso_total is not None else sum(D(str(i[2])) for i in items)
    facturable = p if p >= 1 else D(1)
    flete = _r(facturable * 9)
    envio = _r(flete + 9)
    aplica = boleta >= 200
    tributos = _r(boleta * D("0.24")) if aplica else D(0)
    return {"boleta": float(boleta), "peso_facturable_kg": float(facturable), "costo_flete": float(flete),
            "costo_envio": float(envio), "tributos_aprox": float(tributos),
            "costo_total": float(_r(boleta + envio + tributos)), "aplica_impuesto": aplica,
            "requiere_asesor": boleta > 2000}


def deriva(valor, tax=None, cantidad=1) -> bool:
    v = D(str(valor)) * cantidad
    return v + _tax(v, tax) > 2000


CALCULOS = [
    ("Flete y peso mínimo", [
        ("0.3 kg se cobra como 1 kg", 100, 0.3, None),
        ("0.999 kg, justo bajo el mínimo", 100, 0.999, None),
        ("Exactamente 1 kg", 100, 1, None),
        ("1.5 kg proporcional", 100, 1.5, None),
        ("10 kg proporcional", 100, 10, None),
        ("1.005 kg (1005 g): redondeo de 9.045 a 9.05", 100, 1.005, None),
    ]),
    ("Exoneración: producto + TAX menor a USD 200", [
        ("USD 50, sin tributos", 50, 1, None),
        ("USD 186.91 + TAX 13.08 = 199.99, sin tributos", 186.91, 1, None),
        ("USD 186.92 + TAX 13.08 = 200.00, ya paga (Excel: menor a 200 exonera)", 186.92, 2, None),
        ("USD 199.99 + TAX estimado supera 200: paga", 199.99, 1, None),
        ("USD 199.99 con TAX incluido: sin tributos", 199.99, 1, 0),
        ("USD 120 y 0.5 kg (zapatillas)", 120, 0.5, None),
    ]),
    ("Tributos: 24 % de producto + TAX", [
        ("iPhone USD 1 199, 1 kg (ejemplo del Excel)", 1199, 1, None),
        ("Laptop USD 1 000, 2.5 kg (CP01)", 1000, 2.5, None),
        ("Laptop USD 650, 2.5 kg (ejemplo de Globix)", 650, 2.5, None),
        ("USD 300, 1 kg", 300, 1, None),
        ("USD 500 con peso mínimo (0.4 kg)", 500, 0.4, None),
        ("USD 899.99, 4.2 kg", 899.99, 4.2, None),
    ]),
    ("TAX de la tienda", [
        ("Precio con TAX incluido (cualquier tienda): TAX 0", 650, 2.5, 0),
        ("TAX que indica el cliente (USD 45.50)", 650, 2.5, 45.5),
        ("TAX del cliente que deja la boleta bajo 200", 150, 1, 10),
        ("TAX del cliente que lleva la boleta sobre 200", 190, 1, 15),
        ("Precio con TAX incluido: TAX 0", 250, 1, 0),
        ("USD 1 200, 5 kg con TAX estimado", 1200, 5, None),
    ]),
]

TOPES = [
    ("USD 1 869.15 + TAX = 1 999.99 se cotiza", 1869.15, None),
    ("USD 1 869.16 + TAX = 2 000.00 se cotiza", 1869.16, None),
    ("USD 1 869.17 + TAX = 2 000.01 se deriva", 1869.17, None),
    ("USD 1 999.99 + TAX estimado se deriva", 1999.99, None),
    ("USD 2 000 con TAX incluido se cotiza", 2000, 0),
    ("USD 2 000.01 con TAX incluido se deriva", 2000.01, 0),
]

ERRORES_MOTOR = [
    ("Peso 0 kg: el motor rechaza", 100, 0),
    ("Peso negativo: el motor rechaza", 100, -1),
    ("Valor negativo: el motor rechaza", -5, 1),
]

VALIDACIONES = [
    ("Entradas inválidas", "Valor 0: la validación rechaza",
     {"valor_producto_usd": 0, "peso_kg": 1}, ["producto de 100 dólares, 1 kg"], [], False),
    ("Entradas inválidas", "Falta el peso",
     {"valor_producto_usd": 100, "peso_kg": None}, ["producto de 100 dólares, 1 kg"], [], False),
    ("Entradas inválidas", "Peso no numérico",
     {"valor_producto_usd": 100, "peso_kg": "abc"}, ["producto de 100 dólares, 1 kg"], [], False),
    ("Anclaje al mensaje del cliente", "\"mil dólares\" y \"medio kilo\" en palabras",
     {"valor_producto_usd": 1000, "peso_kg": 0.5}, ["un celular de mil dólares que pesa medio kilo"], [], True),
    ("Anclaje al mensaje del cliente", "Valor y peso dichos por el cliente",
     {"valor_producto_usd": 120, "peso_kg": 1.5}, ["zapatillas de 120 dólares, 1.5 kg"], [], True),
    ("Anclaje al mensaje del cliente", "Valor inventado por el LLM",
     {"valor_producto_usd": 150, "peso_kg": 1.5}, ["zapatillas de 120 dólares, 1.5 kg"], [], False),
    ("Anclaje al mensaje del cliente", "Peso tomado del catálogo",
     {"valor_producto_usd": 1100, "peso_kg": 0.6}, ["quiero un iphone de 1100 dólares"], [0.6], True),
    ("Anclaje al mensaje del cliente", "Peso inventado por el LLM",
     {"valor_producto_usd": 300, "peso_kg": 2}, ["un reloj de 300 dólares"], [], False),
    ("Anclaje al mensaje del cliente", "Peso en gramos (500 g = 0.5 kg)",
     {"valor_producto_usd": 80, "peso_kg": 0.5}, ["un perfume de 80 dólares que pesa 500 gramos"], [], True),
]

CANTIDADES_CALCULO = [
    ("3 polos de USD 20 cada uno, 1 kg en total", 20, 1, None, 3),
    ("2 zapatillas de USD 150: la suma pasa de USD 200 y paga tributos", 150, 2, None, 2),
    ("4 perfumes de USD 45.50 con TAX incluido, 1.6 kg", 45.5, 1.6, 0, 4),
]
CANTIDADES_TOPE = [
    ("3 × USD 700 + TAX supera USD 2 000: se deriva", 700, None, 3),
]
# resultado esperado: entero = cantidad usada, "rechaza" = vuelve al LLM
VALIDACIONES_CANTIDAD = [
    ("\"tres polos\" en palabras", {"cantidad": 3}, ["quiero traer tres polos de 20 dólares cada uno, 1 kg"], 3),
    ("Cantidad inventada por el LLM: rechaza", {"cantidad": 5}, ["quiero traer polos de 20 dólares cada uno, 1 kg"], "rechaza"),
]

# resultado esperado: None = 7 % de referencia, número = TAX que se usa, "rechaza" = vuelve al LLM
VALIDACIONES_TAX = [
    ("Sin datos del TAX: se usa el 7 % de referencia", {}, ["laptop de 650 dólares, 2.5 kg"], None),
    ("Comprar en Amazon ya no basta: rechaza (se usa el 7 %)", {"sin_tax": True}, ["laptop de amazon, 650 dólares, 2.5 kg"], "rechaza"),
    ("Precio con TAX incluido: TAX 0", {"sin_tax": True}, ["son 650 dólares con el tax incluido, 2.5 kg"], 0.0),
    ("sin_tax sin indicio del cliente: rechaza", {"sin_tax": True}, ["laptop de best buy, 650 dólares, 2.5 kg"], "rechaza"),
    ("TAX dicho por el cliente", {"tax_tienda_usd": 45.5}, ["laptop de 650 dólares, el tax fue 45.50, 2.5 kg"], 45.5),
    ("TAX inventado por el LLM: rechaza", {"tax_tienda_usd": 45}, ["laptop de 650 dólares, 2.5 kg"], "rechaza"),
]


# (descripción, [(precio unitario, cantidad, peso kg o None, TAX o None)], peso total o None)
PEDIDOS = [
    ("Polos de Amazon y zapatillas Nike: 171.20 sin tributos (ejemplo aprobado)",
     [(20, 2, 1, None), (120, 1, 1.5, None)], None),
    ("Tres productos, uno con TAX incluido: la suma pasa 200 y paga tributos",
     [(20, 2, 1, None), (120, 1, 1.5, None), (85, 1, 0.6, 0)], None),
    ("Dos productos livianos: el peso total 0.5 kg se cobra como 1 kg", [(30, 1, 0.2, None), (40, 1, 0.3, None)], None),
    ("Peso total dado por el cliente para todo el pedido", [(100, 1, None, None), (150, 1, None, 10)], 3.2),
    ("Cada producto bajo 200 pero la suma sí paga tributos", [(110, 1, 1, None), (110, 1, 1, None)], None),
    ("La suma de productos con TAX pasa USD 2 000: se deriva", [(900, 1, 2, None), (1100, 1, 3, 0)], None),
]


def generar() -> dict:
    casos, n = [], 0

    def nuevo(**c):
        nonlocal n
        n += 1
        casos.append({"id": f"M{n:02d}", **c})

    for categoria, filas in CALCULOS:
        for desc, valor, peso, tax in filas:
            nuevo(categoria=categoria, descripcion=desc, tipo="calculo", valor=valor, peso=peso, tax=tax,
                  esperado=oraculo(valor, peso, tax))
    for desc, valor, tax in TOPES:
        nuevo(categoria="Tope de USD 2 000 (producto + TAX)", descripcion=desc, tipo="tope", valor=valor, tax=tax,
              esperado={"requiere_asesor": deriva(valor, tax)})
    for desc, valor, peso in ERRORES_MOTOR:
        nuevo(categoria="Entradas inválidas", descripcion=desc, tipo="error_motor", valor=valor, peso=peso,
              esperado={"error": True})
    for categoria, desc, args, textos, catalogo, acepta in VALIDACIONES:
        nuevo(categoria=categoria, descripcion=desc, tipo="validacion", args=args, textos=textos,
              catalogo=catalogo, esperado={"acepta": acepta})
    for desc, args, textos, resultado in VALIDACIONES_TAX:
        nuevo(categoria="Anclaje del TAX al mensaje del cliente", descripcion=desc, tipo="validacion_tax",
              args=args, textos=textos, esperado={"resultado": resultado})
    for desc, valor, peso, tax, cantidad in CANTIDADES_CALCULO:
        nuevo(categoria="Cantidad: precio × unidades", descripcion=desc, tipo="calculo", valor=valor, peso=peso,
              tax=tax, cantidad=cantidad, esperado=oraculo(valor, peso, tax, cantidad))
    for desc, valor, tax, cantidad in CANTIDADES_TOPE:
        nuevo(categoria="Cantidad: precio × unidades", descripcion=desc, tipo="tope", valor=valor, tax=tax,
              cantidad=cantidad, esperado={"requiere_asesor": deriva(valor, tax, cantidad)})
    for desc, args, textos, resultado in VALIDACIONES_CANTIDAD:
        nuevo(categoria="Cantidad: precio × unidades", descripcion=desc, tipo="validacion_cantidad",
              args=args, textos=textos, esperado={"resultado": resultado})
    for desc, items, peso_total in PEDIDOS:
        nuevo(categoria="Pedido de varios productos", descripcion=desc, tipo="pedido",
              productos=[{"precio_unitario": p, "cantidad": c, "peso_kg": k, "tax": t} for p, c, k, t in items],
              peso_total=peso_total, esperado=oraculo_pedido(items, peso_total))
    return {"descripcion": __doc__.split("Uso:")[0].strip(), "casos": casos}


if __name__ == "__main__":
    datos = generar()
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{len(datos['casos'])} casos en {RUTA}")
