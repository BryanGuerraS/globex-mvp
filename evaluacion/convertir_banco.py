"""Convierte el banco de pruebas del equipo (bloques INICIO_CASO … FIN_CASO) en casos de evaluar.py.

Uso:
    python evaluacion/convertir_banco.py evaluacion/reservado/Globex_Banco_Pruebas_v3_Pendientes_Depurados.txt
    python evaluacion/convertir_banco.py <lote>.txt --incluir-parciales   # "Validación parcial" al principal

Genera, junto al banco (carpeta ignorada por git):
- casos_reservados.json            -> casos con "Estado de referencia: Listo" (se reportan)
- casos_reservados_pendientes.json -> "Referencia por validar" (se corren aparte, no se reportan
                                      junto a los demás, como pide el propio banco)

Solo se envía al bot lo que está en ENTRADA DESTINADA AL CHATBOT: los mensajes anteriores
del usuario (uno por turno) y el mensaje actual. La referencia del evaluador se traduce a
verificaciones de evaluar.py según la etiqueta "Resultado Globix" y la "Acción esperada".
"""

import json
import os
import re
import sys
from typing import Dict, List, Optional

# Qué tipo de respuesta de Globix acepta cada etiqueta del banco (ver evaluar._tipo_coincide)
TIPOS_ACEPTADOS = {
    "prohibido": ["guardrail"],
    "restringido": ["guardrail", "derivacion"],
    "deriva": ["derivacion", "guardrail"],
    "seguimiento": ["derivacion"],
    "viajero": ["derivacion"],
    "cotiza": ["cotizacion"],
    "falta_peso": ["pide_dato", "libre", "cotizacion"],
    "pide_datos": ["pide_dato", "libre", "menu"],
    "faq": ["faq", "libre", "pide_dato"],
    "fuera_de_alcance": ["fuera_de_alcance", "bloqueado", "libre", "menu", "derivacion"],
    "saludo": ["menu", "libre", "pide_dato"],
}
# Categoría para los KPIs de evaluar.py (K5 usa "guardrail"; K11 usa "alcance")
CATEGORIA_KPI = {"prohibido": "guardrail", "restringido": "guardrail", "fuera_de_alcance": "alcance"}
DERIVA = {"prohibido": False, "restringido": None, "deriva": True, "seguimiento": True, "viajero": True,
          "cotiza": False, "falta_peso": False, "pide_datos": False, "faq": False,
          "fuera_de_alcance": None, "saludo": False}


def _campo(cuerpo: str, nombre: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(nombre)}:[ \t]*(.*)$", cuerpo, re.M)
    return m.group(1).strip() if m else None


def _numero(texto: Optional[str]) -> Optional[float]:
    if not texto:
        return None
    return float(texto.replace(",", "."))


def leer_banco(texto: str) -> List[Dict]:
    """Lee los bloques y devuelve la entrada y la referencia de cada caso, sin interpretar."""
    casos = []
    for cid, cuerpo, cid_fin in re.findall(r"INICIO_CASO (\S+)\n(.*?)\nFIN_CASO (\S+)", texto, re.S):
        if cid != cid_fin:
            raise ValueError(f"Bloque mal cerrado: {cid} / {cid_fin}")
        actual = re.search(r"INICIO_MENSAJE_ACTUAL\n(.*?)\nFIN_MENSAJE_ACTUAL", cuerpo, re.S)
        if not actual:
            raise ValueError(f"{cid}: falta el mensaje actual")
        previos = json.loads(_campo(cuerpo, "Mensajes anteriores del usuario") or "[]")
        casos.append({
            "id": cid,
            "procedencia": _campo(cuerpo, "Procedencia"),
            "estado_referencia": _campo(cuerpo, "Estado de referencia"),
            "categoria_banco": _campo(cuerpo, "Categoría"),
            "accion": _campo(cuerpo, "Acción esperada"),
            "resultado": _campo(cuerpo, "Resultado Globix"),
            "valor": _numero(_campo(cuerpo, "Valor USD")),
            "peso": _numero(_campo(cuerpo, "Peso kg")),
            "duda": (_campo(cuerpo, "Duda") or "no").lower(),
            "origen": _campo(cuerpo, "Caso real de origen"),
            "estado_inicial": json.loads(_campo(cuerpo, "Estado inicial") or "{}"),
            "mensajes": [p["texto"] for p in previos] + [actual.group(1).strip()],
        })
    return casos


def a_caso_evaluar(c: Dict) -> Dict:
    """Traduce un caso del banco al formato de evaluar.py."""
    etiqueta = c["resultado"]
    if etiqueta not in TIPOS_ACEPTADOS:
        raise ValueError(f"{c['id']}: etiqueta desconocida {etiqueta!r}")
    esperado: Dict = {"tipo_final": TIPOS_ACEPTADOS[etiqueta]}
    if etiqueta == "cotiza":
        esperado["cotizacion"] = {"valor": c["valor"], "peso": c["peso"]}
        esperado["cotiza"] = True
    elif etiqueta != "falta_peso":  # falta_peso: puede pedir el peso o usar el catálogo
        esperado["cotiza"] = False
    deriva = DERIVA[etiqueta]
    if "o derivar" in (c["accion"] or "").lower():  # "Orientar o derivar": las dos son válidas
        deriva = None
    if deriva is not None:
        esperado["deriva"] = deriva
    return {
        "id": c["id"],
        "categoria": CATEGORIA_KPI.get(etiqueta, etiqueta),
        "descripcion": f"{c['categoria_banco']} · {c['accion']}",
        "mensajes": c["mensajes"],
        "esperado": esperado,
        "banco": {
            "procedencia": c["procedencia"],
            "grupo": c["origen"] or c["id"],  # una variante se agrupa con su caso real
            "segmento": c["categoria_banco"],
            "resultado_globix": etiqueta,
            "accion": c["accion"],
            "estado_referencia": c["estado_referencia"],
            "duda": c["duda"],
            "estado_inicial": c["estado_inicial"],
        },
    }


# Estados que entran al archivo principal. "Validación parcial" (lote nuevo del 12/11):
# la referencia tiene una parte abierta (p. ej. el total de tributos), pero los checks
# automáticos (tipo de respuesta, si cotiza, si deriva, precio y peso) sí son evaluables.
ESTADO_LISTO = "Listo"
ESTADO_PARCIAL = "Validación parcial"


def convertir(ruta_banco: str, incluir_parciales: bool = False) -> Dict[str, str]:
    with open(ruta_banco, encoding="utf-8") as f:
        banco = leer_banco(f.read())
    principales = {ESTADO_LISTO} | ({ESTADO_PARCIAL} if incluir_parciales else set())
    listos = [a_caso_evaluar(c) for c in banco if c["estado_referencia"] in principales]
    pendientes = [a_caso_evaluar(c) for c in banco if c["estado_referencia"] not in principales]
    carpeta = os.path.dirname(os.path.abspath(ruta_banco))
    rutas = {}
    for nombre, casos, desc in (
        ("casos_reservados.json", listos, "Set RESERVADO (banco del equipo, estado Listo). "
         "Se corre una vez, sin ajustar el prompt antes. No usar para ajustar."),
        ("casos_reservados_pendientes.json", pendientes, "Casos del banco con referencia por "
         "validar: se reportan aparte."),
    ):
        rutas[nombre] = os.path.join(carpeta, nombre)
        with open(rutas[nombre], "w", encoding="utf-8") as f:
            json.dump({"descripcion": desc, "version": os.path.basename(ruta_banco), "casos": casos},
                      f, ensure_ascii=False, indent=1)
    return rutas


if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if a != "--incluir-parciales"]
    if len(argumentos) != 1:
        sys.exit(__doc__)
    for nombre, ruta in convertir(argumentos[0], "--incluir-parciales" in sys.argv).items():
        with open(ruta, encoding="utf-8") as f:
            print(f"{nombre}: {len(json.load(f)['casos'])} casos -> {ruta}")
