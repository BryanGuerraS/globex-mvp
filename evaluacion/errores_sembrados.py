"""Validación del LLM juez con errores sembrados.

Toma conversaciones reales de Globix (una hoja de revision_humana.py), les
inserta UN error conocido y mide si el juez lo detecta. Así se estima la
sensibilidad del juez sin revisores humanos: el error sembrado es la etiqueta
de referencia. La especificidad se mide aparte, con las conversaciones sin
modificar que los checks automáticos dan por correctas (juez_llm.py).

Uso:
    python evaluacion/errores_sembrados.py --hoja evaluacion/reportes/revision_humana/hoja_revisor_A.csv --por-tipo 5
"""

import argparse
import os
import random
import re
import sys
from datetime import datetime
from typing import Callable, Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion import juez_llm as jz  # noqa: E402
from evaluacion import revision_humana as rh  # noqa: E402
from metricas import clopper_pearson  # noqa: E402

RE_FLETE = re.compile(r"(Flete aéreo:\*? USD [\d.,]+ \()([\d.]+)( kg\))")
SIN_DERIVAR = re.compile(r"asesor (revisará|te escribirá|se comunicará)|te paso con|derivo", re.I)
MENU = ("GLOBIX: ¡Hola! 👋 Soy Globix, el asistente virtual de Globex. ¿En qué te puedo ayudar?\n"
        "[Botones: Cotizar envío | Rastrear paquete | Otras consultas]")


MARCAS_FAQ = ("Plazos de entrega", "Métodos de pago", "almacén en Miami", "Cobertura a Nivel Nacional", "en 4 pasos")


def _consulta_estandar(texto: str) -> bool:
    """Cotización o pregunta frecuente: casos donde el error sembrado es inequívoco."""
    return bool(RE_FLETE.search(texto)) or any(m in texto for m in MARCAS_FAQ)


def _lineas_globix(texto: str) -> List[int]:
    return [i for i, l in enumerate(texto.split("\n")) if l.startswith("GLOBIX:")]


def _agregar_al_final(texto: str, linea: str) -> str:
    return texto.rstrip() + "\n" + linea


def _peso_cambiado(texto: str) -> Optional[str]:
    m = RE_FLETE.search(texto)
    if not m:
        return None
    nuevo = f"{float(m.group(2)) * 10:.1f}"
    return texto[:m.start(2)] + nuevo + texto[m.end(2):]


def _plazo_inventado(texto: str) -> Optional[str]:
    if not _lineas_globix(texto):
        return None
    return _agregar_al_final(texto, "GLOBIX: Además, tu paquete llega garantizado en 48 horas desde que compras en la tienda. ✈️")


def _dato_repetido(texto: str) -> Optional[str]:
    """Justo antes de la cotización (el cliente ya dio todo), vuelve a pedir el precio y el modelo."""
    lineas = texto.split("\n")
    i_flete = next((i for i, l in enumerate(lineas) if RE_FLETE.search(l)), None)
    if i_flete is None:
        return None
    i_bot = max((i for i in range(i_flete + 1) if lineas[i].startswith("GLOBIX:")), default=None)
    if i_bot is None:
        return None
    pregunta = "GLOBIX: Antes de seguir, ¿me confirmas el precio del producto en USD y el modelo exacto?"
    return "\n".join([*lineas[:i_bot], pregunta, *lineas[i_bot:]])


def _descuento(texto: str) -> Optional[str]:
    if not RE_FLETE.search(texto):
        return None
    return _agregar_al_final(texto, "GLOBIX: Si confirmas tu compra hoy, te hago un 15 % de descuento en el flete. 🙌")


def _derivacion_innecesaria(texto: str) -> Optional[str]:
    if not _consulta_estandar(texto) or SIN_DERIVAR.search(texto) or "asesor" in texto.split("\n")[0].lower():
        return None
    return _agregar_al_final(texto, "GLOBIX: Te paso con un asesor para que continúe tu atención. Un momento, por favor.")


def _no_atiende(texto: str) -> Optional[str]:
    lineas = texto.split("\n")
    clientes = [l for l in lineas if l.startswith("CLIENTE:")]
    if not _consulta_estandar(texto) or len(clientes) != 1 or len(clientes[0]) < 25:  # pedido concreto en un mensaje
        return None
    return clientes[0] + "\n" + MENU


# tipo -> (criterio que debe fallar, función que siembra el error o devuelve None si no aplica)
TIPOS: Dict[str, tuple] = {
    "no_atiende": ("C1_necesidad", _no_atiende),
    "peso_cambiado": ("C2_informacion", _peso_cambiado),
    "plazo_inventado": ("C2_informacion", _plazo_inventado),
    "dato_repetido": ("C3_datos", _dato_repetido),
    "descuento": ("C4_procedimiento", _descuento),
    "derivacion_innecesaria": ("C5_derivacion", _derivacion_innecesaria),
}


def sembrar(filas: List[Dict], por_tipo: int, semilla: int = 11) -> List[Dict]:
    """Devuelve filas nuevas (id S###) con un error sembrado cada una, sin repetir conversación si se puede."""
    azar = random.Random(semilla)
    usadas, sembradas = set(), []
    for tipo, (criterio, fn) in TIPOS.items():
        candidatas = [f for f in filas if fn(f["conversacion"]) is not None]
        azar.shuffle(candidatas)
        candidatas.sort(key=lambda f: f["id"] in usadas)  # primero las no usadas
        for f in candidatas[:por_tipo]:
            usadas.add(f["id"])
            sembradas.append({"origen": f["id"], "tipo": tipo, "criterio": criterio,
                              "conversacion": fn(f["conversacion"])})
    azar.shuffle(sembradas)
    for i, s in enumerate(sembradas, 1):
        s["id"] = f"S{i:03d}"
    return sembradas


def medir_deteccion(sembradas: List[Dict], juez: Dict[str, Dict]) -> Dict:
    """Por tipo: % en que el juez marca la conversación como incorrecta y % en el criterio exacto."""
    por_tipo: Dict[str, Dict] = {}
    for s in sembradas:
        v = juez.get(s["id"])
        if not v or rh.atencion_correcta(v) is None:
            continue
        t = por_tipo.setdefault(s["tipo"], {"criterio": s["criterio"], "n": 0, "detectados": 0, "exactos": 0})
        t["n"] += 1
        t["detectados"] += rh.atencion_correcta(v) == "N"
        t["exactos"] += v.get(s["criterio"]) == "N"
    total = {k: sum(t[k] for t in por_tipo.values()) for k in ("n", "detectados", "exactos")}
    return {"por_tipo": por_tipo, "total": total}


def _fila_tabla(nombre: str, criterio: str, t: Dict) -> str:
    def celda(k):
        li, ls = clopper_pearson(t[k], t["n"])
        return f"{t[k]}/{t['n']} ({t[k] / t['n']:.0%}; IC {li:.0%}–{ls:.0%})"
    return f"| {nombre} | {criterio} | {celda('detectados')} | {celda('exactos')} |"


def reporte(deteccion: Dict, modelo: str) -> str:
    lineas = [f"# Validación del juez con errores sembrados · {datetime.now():%d/%m/%Y %H:%M}", "",
              f"Juez: `{modelo}`. Cada conversación tiene un solo error conocido.", "",
              "| Error sembrado | Criterio esperado | Detectado (atención incorrecta) | En el criterio exacto |",
              "| --- | --- | --- | --- |"]
    for tipo, t in deteccion["por_tipo"].items():
        lineas.append(_fila_tabla(tipo, rh.CRITERIOS[t["criterio"]], t))
    if deteccion["total"]["n"]:
        lineas.append(_fila_tabla("**Total**", "", deteccion["total"]))
    return "\n".join(lineas) + "\n"


def main(argv=None, llamar: Optional[Callable] = None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hoja", required=True)
    parser.add_argument("--por-tipo", type=int, default=5)
    parser.add_argument("--semilla", type=int, default=11)
    parser.add_argument("--modelo", default=jz.MODELO_JUEZ)
    args = parser.parse_args(argv)

    carpeta = os.path.dirname(os.path.abspath(args.hoja))
    sembradas = sembrar(rh.leer_csv(args.hoja), args.por_tipo, args.semilla)
    ruta_hoja = os.path.join(carpeta, "hoja_sembrada.csv")
    rh.escribir_csv(ruta_hoja, rh.COLUMNAS_HOJA, [{"id": s["id"], "conversacion": s["conversacion"]} for s in sembradas])
    rh.escribir_csv(os.path.join(carpeta, "clave_sembrada.csv"), ["id", "origen", "tipo", "criterio"], sembradas)

    llamar = llamar or jz.llamador_groq(args.modelo)
    ruta_juez = os.path.join(carpeta, "hoja_juez_sembrada.csv")
    jz.juzgar_hoja(ruta_hoja, ruta_juez, llamar)
    texto = reporte(medir_deteccion(sembradas, rh.leer_hoja(ruta_juez)), args.modelo)
    ruta_md = os.path.join(carpeta, f"reporte_sembrados_{datetime.now():%Y%m%d_%H%M}.md")
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Reporte: {ruta_md}")


if __name__ == "__main__":
    main()
