"""Convierte el banco de cotizaciones del equipo (U01-01 … U08-05) a casos de evaluar.py.

Entrada: la carpeta con 01_Preguntas_Cotizaciones_Globex.txt y 03_Respuestas_Cotizaciones_Globex.txt
(bloques "Uxx-yy" seguidos de sus líneas). Salida: casos_cotizaciones.json en la misma carpeta.

Cada caso espera una cotización con el peso del cliente y el TOTAL de la respuesta del banco
(decisión del 14/11: el % de cotizaciones correctas evalúa solo el total). Antes de escribir, el
total del banco se recalcula con el oráculo independiente de generar_casos_motor.py con las reglas
vigentes; si alguno no coincide, se informa y el caso se marca para revisión.

Uso: python evaluacion/convertir_banco_cotizaciones.py <carpeta del banco>
"""

import json
import os
import re
import sys
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion.generar_casos_motor import oraculo_pedido  # noqa: E402

PREGUNTAS = "01_Preguntas_Cotizaciones_Globex.txt"
RESPUESTAS = "03_Respuestas_Cotizaciones_Globex.txt"
_ID = re.compile(r"^U\d{2}-\d{2}$")


def leer_bloques(ruta: str) -> Dict[str, List[str]]:
    bloques: Dict[str, List[str]] = {}
    actual = None
    with open(ruta, encoding="utf-8-sig") as f:
        for linea in f:
            linea = linea.strip()
            if _ID.match(linea):
                actual = linea
                bloques[actual] = []
            elif actual and linea:
                bloques[actual].append(linea)
    return bloques


def numero(texto: str) -> float:
    """'1.234,50' o '128,40' o '9.00' -> float."""
    t = texto.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def _usd(linea: str) -> float:
    return numero(re.search(r"USD\s*([\d.,]+)", linea).group(1))


def esperado_del_banco(respuesta: List[str], pregunta: str) -> Dict:
    campos = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in respuesta if ":" in l}
    clave_tax = next(k for k in campos if k.startswith("TAX de tienda"))
    peso = numero(re.search(r"embalaje es\s*([\d.,]+)\s*kg", pregunta).group(1))
    if "Precio de compra con TAX incluido" in campos:
        precio, tax = _usd(campos["Precio de compra con TAX incluido"]), 0.0
        tipo_tax = "incluido_sin_desglose"
    else:
        precio, tax = _usd(campos["Producto sin TAX"]), _usd(campos[clave_tax])
        tipo_tax = ("estimado_7" if "estimado" in clave_tax else
                    "incluido_desglosado" if "incluido" in clave_tax else "confirmado")
    return {"total": _usd(campos["Total estimado"]), "precio": precio, "tax": tax, "tipo_tax": tipo_tax,
            "peso": peso, "flete": _usd(campos["Flete aéreo"]), "desaduanaje": _usd(campos["Desaduanaje"]),
            "tributos": _usd(campos["Tributos de importación estimados"])}


def convertir(carpeta: str) -> Dict:
    preguntas = leer_bloques(os.path.join(carpeta, PREGUNTAS))
    respuestas = leer_bloques(os.path.join(carpeta, RESPUESTAS))
    casos, revisar = [], []
    for cid, resp in respuestas.items():
        pregunta = " ".join(preguntas[cid])
        e = esperado_del_banco(resp, pregunta)
        tax_oraculo = None if e["tipo_tax"] == "estimado_7" else e["tax"]
        oraculo = oraculo_pedido([(e["precio"], 1, e["peso"], tax_oraculo)])
        if abs(oraculo["costo_total"] - e["total"]) > 0.005:
            revisar.append({"id": cid, "banco": e["total"], "reglas_vigentes": oraculo["costo_total"]})
        casos.append({
            "id": cid, "categoria": "cotizacion", "universo": cid[:3],
            "descripcion": f"Banco de cotizaciones del equipo ({e['tipo_tax'].replace('_', ' ')})",
            "mensajes": [pregunta],
            "esperado": {"tipo_final": ["cotizacion"], "cotiza": True, "deriva": False,
                         "cotizacion": {"peso": e["peso"], "total": e["total"]}},
            "banco": {**e, "total_reglas_vigentes": oraculo["costo_total"]},
        })
    return {"descripcion": "Banco de cotizaciones simples del equipo (40), verificado con las reglas del 14/11",
            "casos": casos, "revisar": revisar}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit(__doc__)
    carpeta = os.path.abspath(argv[0])
    datos = convertir(carpeta)
    ruta = os.path.join(carpeta, "casos_cotizaciones.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{len(datos['casos'])} casos en {ruta}")
    print(f"Totales que no coinciden con las reglas vigentes: {len(datos['revisar'])}")
    for r in datos["revisar"]:
        print(f"  {r['id']}: banco USD {r['banco']:.2f}, reglas vigentes USD {r['reglas_vigentes']:.2f}")


if __name__ == "__main__":
    main()
