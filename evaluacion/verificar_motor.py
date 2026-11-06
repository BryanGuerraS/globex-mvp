"""Verificación del motor de cotización con los 36 casos sintéticos.

Los valores esperados de `casos_motor.json` salen de un oráculo independiente en
Decimal (redondeo comercial a 2 decimales), no del propio motor. Cada caso compara
el resultado de `GlobexPricingEngine` (o de `validar_argumentos_cotizacion`) contra
lo esperado, al centavo.

Uso: python evaluacion/verificar_motor.py
"""

import json
import os
import sys
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from metricas import clopper_pearson  # noqa: E402
from pricing_engine import GlobexPricingEngine  # noqa: E402
from validaciones import validar_argumentos_cotizacion  # noqa: E402

CASOS_MOTOR = os.path.join(REPO, "evaluacion", "casos_motor.json")
CAMPOS_MONTO = ("peso_facturable_kg", "costo_flete", "costo_envio", "tributos_aprox", "costo_total")


def cargar_casos(ruta: str = CASOS_MOTOR) -> List[Dict]:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)["casos"]


def verificar_caso(caso: Dict) -> Dict:
    """Devuelve {'ok': bool, 'diferencias': [...], 'obtenido': ...} para un caso."""
    esperado, tipo = caso["esperado"], caso["tipo"]
    diferencias: List[str] = []
    obtenido: Dict = {}
    if tipo == "calculo":
        obtenido = GlobexPricingEngine.calcular(caso["valor"], caso["peso"])
        for campo in CAMPOS_MONTO:
            if abs(obtenido[campo] - esperado[campo]) > 0.0049:
                diferencias.append(f"{campo}: esperado {esperado[campo]:.2f}, motor {obtenido[campo]:.2f}")
        if obtenido["aplica_impuesto"] != esperado["aplica_impuesto"]:
            diferencias.append("aplica_impuesto distinto")
        if GlobexPricingEngine.requiere_asesor(caso["valor"]) != esperado["requiere_asesor"]:
            diferencias.append("requiere_asesor distinto")
        total = f"USD {esperado['costo_total']:,.2f}"
        if total not in GlobexPricingEngine.formatear_mensaje_whatsapp(obtenido):
            diferencias.append(f"el mensaje no muestra {total}")
    elif tipo == "tope":
        obtenido = {"requiere_asesor": GlobexPricingEngine.requiere_asesor(caso["valor"])}
        if obtenido != esperado:
            diferencias.append(f"requiere_asesor: esperado {esperado['requiere_asesor']}, motor {obtenido['requiere_asesor']}")
    elif tipo == "error_motor":
        try:
            GlobexPricingEngine.calcular(caso["valor"], caso["peso"])
            obtenido = {"error": False}
            diferencias.append("el motor aceptó una entrada inválida")
        except ValueError:
            obtenido = {"error": True}
    elif tipo == "validacion":
        r = validar_argumentos_cotizacion(caso["args"], caso["textos"], caso["catalogo"])
        obtenido = {"acepta": isinstance(r, tuple)}
        if obtenido["acepta"] != esperado["acepta"]:
            diferencias.append(f"validación: esperado {'aceptar' if esperado['acepta'] else 'rechazar'}, "
                               f"obtuvo {'aceptar' if obtenido['acepta'] else 'rechazar'}")
    else:
        raise ValueError(f"Tipo de caso desconocido: {tipo}")
    return {"id": caso["id"], "categoria": caso["categoria"], "descripcion": caso["descripcion"],
            "ok": not diferencias, "diferencias": diferencias}


def verificar_todos(casos: List[Dict] = None) -> Dict:
    casos = casos if casos is not None else cargar_casos()
    resultados = [verificar_caso(c) for c in casos]
    por_categoria: Dict[str, Dict] = {}
    for r in resultados:
        c = por_categoria.setdefault(r["categoria"], {"total": 0, "ok": 0})
        c["total"] += 1
        c["ok"] += r["ok"]
    ok = sum(r["ok"] for r in resultados)
    return {"total": len(resultados), "ok": ok, "ic95": list(clopper_pearson(ok, len(resultados))),
            "por_categoria": por_categoria, "resultados": resultados}


if __name__ == "__main__":
    res = verificar_todos()
    print(f"Motor: {res['ok']}/{res['total']} casos correctos")
    for cat, c in res["por_categoria"].items():
        print(f"  {cat}: {c['ok']}/{c['total']}")
    for r in res["resultados"]:
        if not r["ok"]:
            print(f"  ❌ {r['id']} {r['descripcion']}: {'; '.join(r['diferencias'])}")
