"""Resumen global de KPIs de Globix en PDF, por categoría y contra las metas mínimas.

Junta tres fuentes:
1. los 36 casos sintéticos del motor (`verificar_motor.py`, se corren al momento);
2. la suite de pruebas automatizadas (pytest, se corre al momento);
3. la última evaluación conversacional con el LLM real (`resultados_*.json` de
   `evaluar.py`; se elige la más reciente que cubra el set completo).

Uso:
    python evaluacion/resumen_kpis.py [--eval reportes/resultados_X.json] [--sin-pytest]
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from reportlab.graphics.shapes import Drawing, Line, Rect, String  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from database import ahora  # noqa: E402
from evaluacion.kpis_minimos import KPIS_MINIMOS, corridas_necesarias, evaluar_estado, garantia  # noqa: E402
from evaluacion.reporte_pdf import BORDE, E, GRIS, LOGO, MORADO, NARANJA, _p, _tabla  # noqa: E402
from evaluacion.verificar_motor import verificar_todos  # noqa: E402
from metricas import clopper_pearson  # noqa: E402
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402

registerFontFamily("Vera", normal="Vera", bold="VeraBd", italic="Vera", boldItalic="VeraBd")

REPORTES = os.path.join(REPO, "evaluacion", "reportes")
TINTA = colors.HexColor("#27272A")
CUADRICULA = colors.HexColor("#E4E4E7")
IC_COLOR = colors.HexColor("#52525B")
ESTADOS = {  # color de fondo y de texto de cada estado (siempre con su etiqueta)
    "Cumple": (colors.HexColor("#DCFCE7"), colors.HexColor("#166534")),
    "Cumple (falta n)": (colors.HexColor("#FEF3C7"), colors.HexColor("#92400E")),
    "No cumple": (colors.HexColor("#FEE2E2"), colors.HexColor("#991B1B")),
    "Sin datos": (colors.HexColor("#F4F4F5"), colors.HexColor("#52525B")),
}
NOMBRES_CATEGORIA_EVAL = {
    "cotizacion": "Cotización directa", "catalogo": "Peso de catálogo", "palabras": "Montos en palabras",
    "datos_faltantes": "Datos faltantes", "tope": "Tope USD 1 200", "guardrail": "Mercancía restringida",
    "faq": "Preguntas frecuentes", "seguimiento": "Seguimiento", "viajero": "Viajero",
    "asesor": "Pedido de asesor", "alcance": "Fuera de alcance", "adversarial": "Adversarial",
    "multiturno": "Varios turnos", "saludo": "Saludo", "derivacion": "Debe derivar",
    "no_derivar": "No debe derivar", "falso_amigo": "Falsos amigos del guardrail",
}


# ------------------------------------------------------------------ Datos

def correr_pytest() -> Dict:
    """Corre la suite y cuenta pasadas, fallidas y fallos conocidos (xfail)."""
    salida = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:warnings"],
                            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ultima = (salida.stdout.strip().splitlines() or [""])[-1]
    cuenta = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|xfailed|error|errors)", ultima)}
    return {"passed": cuenta.get("passed", 0), "failed": cuenta.get("failed", 0) + cuenta.get("error", 0)
            + cuenta.get("errors", 0), "xfailed": cuenta.get("xfailed", 0), "linea": ultima}


def ultima_evaluacion_completa() -> Optional[str]:
    """La corrida más reciente de evaluar.py con el set completo (no las de --solo)."""
    mejor = None
    for ruta in sorted(glob.glob(os.path.join(REPORTES, "resultados_*.json"))):
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        if len(datos.get("resultados", {})) >= 20:
            mejor = ruta
    return mejor


def _casos_eval(meta: Dict) -> Dict[str, Dict]:
    ruta = meta.get("archivo_casos", "")
    ruta = ruta if os.path.isabs(ruta) else os.path.join(REPO, ruta.replace("\\", os.sep))
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    lista = datos if isinstance(datos, list) else next(v for v in datos.values() if isinstance(v, list))
    return {c["id"]: c for c in lista}


def por_categoria_eval(evaluacion: Dict) -> List[Dict]:
    """pass^1 por categoría de caso de la evaluación conversacional."""
    casos = _casos_eval(evaluacion["meta"])
    grupos: Dict[str, List[bool]] = {}
    for id_caso, corridas in evaluacion["resultados"].items():
        cat = casos.get(id_caso, {}).get("categoria", "otros")
        grupos.setdefault(cat, []).extend(r["exito"] for r in corridas)
    filas = []
    for cat, exitos in sorted(grupos.items(), key=lambda kv: NOMBRES_CATEGORIA_EVAL.get(kv[0], kv[0])):
        ok, n = sum(exitos), len(exitos)
        filas.append({"categoria": NOMBRES_CATEGORIA_EVAL.get(cat, cat), "ok": ok, "n": n,
                      "valor": ok / n, "ic95": list(clopper_pearson(ok, n))})
    return filas


def construir_kpis(motor: Dict, pruebas: Optional[Dict], evaluacion: Optional[Dict]) -> List[Dict]:
    """Une cada meta con su valor medido (y su IC si es una proporción)."""
    medidos: Dict[str, Tuple[Optional[float], Optional[List[float]], str]] = {
        "V1_motor": (motor["ok"] / motor["total"], None, f"{motor['ok']}/{motor['total']}"),
    }
    if pruebas:
        total = pruebas["passed"] + pruebas["failed"]
        medidos["V2_pruebas"] = (pruebas["passed"] / total if total else None, None,
                                 f"{pruebas['passed']}/{total}" + (f" (+{pruebas['xfailed']} conocido)"
                                                                     if pruebas["xfailed"] else ""))
    if evaluacion:
        for clave, k in evaluacion["kpis"].items():
            if k and k.get("n"):
                medidos[clave] = (k["valor"], k["ic95"], f"{k['exitos']}/{k['n']}")
        cl = evaluacion.get("costo_latencia", {})
        espera = cl.get("latencia_total_cliente", {})
        debounce = 5.0  # evaluar.py mide sin la espera de 5 s del debounce
        sin = cl.get("latencia_total_sin_limites", {})
        if espera.get("p50_ms") is not None:
            for p in ("p50", "p95"):
                detalle = "incluye 5 s"
                if sin.get(f"{p}_ms") is not None and sin[f"{p}_ms"] < espera[f"{p}_ms"] - 1:
                    detalle += f"; sin cuota Groq: {sin[f'{p}_ms'] / 1000 + debounce:.1f} s"
                medidos[f"espera_{p}_s"] = (espera[f"{p}_ms"] / 1000 + debounce, None, detalle)
        if cl.get("costo_por_1000_conversaciones_usd") is not None:
            medidos["costo_1000_usd"] = (cl["costo_por_1000_conversaciones_usd"], None, "")
    filas = []
    for meta in KPIS_MINIMOS:
        valor, ic, detalle = medidos.get(meta["clave"], (None, None, ""))
        filas.append({**meta, "valor": valor, "ic95": ic, "detalle": detalle,
                      "estado": evaluar_estado(meta, valor, ic)})
    return filas


# ------------------------------------------------------------------ Formato

def _fmt(valor: Optional[float], unidad: str) -> str:
    if valor is None:
        return "—"
    if unidad == "%":
        return f"{valor * 100:.1f} %"
    if unidad == "USD":
        return f"USD {valor:.2f}"
    return f"{valor:.1f} {unidad}"


def _meta_txt(k: Dict) -> str:
    signo = "≥" if k["sentido"] == "min" else "≤"
    texto = f"{signo} {_fmt(k['meta'], k['unidad'])}"
    if k.get("unidad") == "%" and garantia(k) != k["meta"]:
        texto += f" (IC ≥ {garantia(k) * 100:.0f} %)"
    return texto


def _celda_estado(estado: str):
    return Paragraph(f'<font color="#{ESTADOS[estado][1].hexval()[2:]}">{estado}</font>', E["celda_neg"])


def _rico(texto: str, estilo: str = "texto"):
    """Párrafo con marcado (<b>) escrito por nosotros, sin escapar."""
    return Paragraph(texto, E[estilo])


def _estilo_estados(tabla: Table, estados: List[str], columna: int):
    reglas = []
    for i, estado in enumerate(estados, start=1):
        fondo, texto = ESTADOS[estado]
        reglas += [("BACKGROUND", (columna, i), (columna, i), fondo), ("TEXTCOLOR", (columna, i), (columna, i), texto)]
    tabla.setStyle(TableStyle(reglas))


def grafico_barras(filas: List[Dict], ancho: float = 180 * mm, meta: Optional[float] = None) -> Drawing:
    """Barras horizontales 0–100 %: valor, IC 95 % (bigote gris) y meta (marca naranja).

    filas: [{"etiqueta", "valor", "ic95" (opcional), "meta" (opcional)}]
    """
    alto_fila, izq, der, arriba, abajo = 10 * mm, 62 * mm, 16 * mm, 4 * mm, 9 * mm
    alto = arriba + abajo + alto_fila * len(filas)
    d = Drawing(ancho, alto)
    plot = ancho - izq - der

    def x(p):
        return izq + plot * max(0.0, min(1.0, p))

    for t in (0, 0.25, 0.5, 0.75, 1.0):  # cuadrícula recesiva
        d.add(Line(x(t), abajo, x(t), alto - arriba, strokeColor=CUADRICULA, strokeWidth=0.5))
        d.add(String(x(t), abajo - 4 * mm, f"{t * 100:.0f} %", fontName="Vera", fontSize=6.5,
                     fillColor=GRIS, textAnchor="middle"))
    for i, f in enumerate(filas):
        cy = alto - arriba - alto_fila * (i + 0.5)
        d.add(String(izq - 3 * mm, cy - 2.2, f["etiqueta"][:42], fontName="Vera", fontSize=7.5,
                     fillColor=TINTA, textAnchor="end"))
        if f.get("valor") is None:
            d.add(String(x(0) + 2, cy - 2.2, "sin datos", fontName="Vera", fontSize=7, fillColor=GRIS))
            continue
        barra = 3.6 * mm
        d.add(Rect(x(0), cy - barra / 2, max(0.5, x(f["valor"]) - x(0)), barra, rx=1.2, ry=1.2,
                   fillColor=MORADO, strokeColor=None))
        if f.get("ic95"):
            li, ls = f["ic95"]
            yi = cy - barra / 2 - 1.4 * mm
            d.add(Line(x(li), yi, x(ls), yi, strokeColor=IC_COLOR, strokeWidth=1))
            for extremo in (li, ls):
                d.add(Line(x(extremo), yi - 0.9 * mm, x(extremo), yi + 0.9 * mm, strokeColor=IC_COLOR, strokeWidth=1))
        m = f.get("meta", meta)
        if m is not None:
            d.add(Line(x(m), cy - 3 * mm, x(m), cy + 3 * mm, strokeColor=NARANJA, strokeWidth=2))
        etiqueta = "100 %" if f["valor"] >= 0.9995 else f"{f['valor'] * 100:.1f} %"
        d.add(String(x(1.0) + 2 * mm, cy - 2.2, etiqueta, fontName="VeraBd", fontSize=7.5,
                     fillColor=TINTA))
    return d


def _leyenda_grafico():
    return _p("Barra morada: valor medido · línea gris bajo la barra: IC 95 % (Clopper-Pearson) · marca naranja: meta mínima.",
              "chico")


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(NARANJA)
    canvas.setLineWidth(2)
    canvas.line(15 * mm, 287 * mm, 195 * mm, 287 * mm)
    canvas.setFont("Vera", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(15 * mm, 10 * mm, "Globex Courier · Resumen de KPIs de Globix · Capstone UTEC")
    canvas.drawRightString(195 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()


# ------------------------------------------------------------------ PDF

def generar_resumen_pdf(kpis: List[Dict], motor: Dict, pruebas: Optional[Dict], evaluacion: Optional[Dict],
                        ruta_eval: Optional[str], ruta: str) -> str:
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="Resumen de KPIs de Globix")
    h: List = []
    if os.path.exists(LOGO):
        h.append(Image(LOGO, width=42 * mm, height=42 * mm * 0.3, kind="proportional", hAlign="LEFT"))
        h.append(Spacer(1, 4 * mm))
    h.append(_p("Resumen de KPIs de Globix", "titulo"))
    fecha = ahora().strftime("%d/%m/%Y %H:%M")
    fuente_eval = (f"evaluación conversacional del {evaluacion['meta']['fecha']} "
                   f"({len(evaluacion['resultados'])} casos × {evaluacion['meta']['repeticiones']} repeticiones, "
                   f"{evaluacion['meta']['modelo']})") if evaluacion else "sin evaluación conversacional"
    h.append(_p(f"Generado el {fecha} (hora de Lima). Fuentes: 36 casos del motor, pruebas automatizadas y "
                f"{fuente_eval}.", "chico"))
    h.append(Spacer(1, 5 * mm))

    # --- Tablero: cuántos KPIs cumplen
    conteo = {e: sum(k["estado"] == e for k in kpis) for e in ESTADOS}
    celdas = [[_rico(f'<font color="#{ESTADOS[e][1].hexval()[2:]}">{conteo[e]}</font>', "titulo") for e in ESTADOS],
              [_celda_estado(e) for e in ESTADOS]]
    tablero = Table(celdas, colWidths=[45 * mm] * 4)
    estilo = [("BOX", (i, 0), (i, 1), 0.6, BORDE) for i in range(4)]
    estilo += [("BACKGROUND", (i, 0), (i, 1), ESTADOS[e][0]) for i, e in enumerate(ESTADOS)]
    estilo += [("TEXTCOLOR", (i, 0), (i, 1), ESTADOS[e][1]) for i, e in enumerate(ESTADOS)]
    estilo += [("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 5)]
    tablero.setStyle(TableStyle(estilo))
    h += [tablero, Spacer(1, 3 * mm)]
    h.append(_rico("<b>Cumple</b>: incluso el extremo desfavorable del IC 95 % alcanza la meta. "
                "<b>Cumple (falta n)</b>: el valor alcanza la meta, pero con pocos casos el IC todavía no lo "
                "garantiza (con 30/30 aciertos el IC solo asegura ≥ 88.4 %). <b>No cumple</b>: el valor está "
                "por debajo de la meta. <b>Sin datos</b>: se medirá más adelante. Los KPIs de 100 % (motor, cotización "
                "indebida, guardrail) no toleran ni un error.", "chico"))

    # --- Tabla global
    h.append(_p("KPIs globales contra la meta mínima", "h2"))
    filas = [["KPI", "Valor", "IC 95 %", "Meta", "n mín.", "Estado"]]
    for k in kpis:
        ic = f"{k['ic95'][0] * 100:.1f}–{k['ic95'][1] * 100:.1f} %" if k["ic95"] else (k["detalle"] or "—")
        necesarias = corridas_necesarias(k)
        filas.append([_p(k["nombre"], "celda"), _p(_fmt(k["valor"], k["unidad"]) + (
            f"  ({k['detalle']})" if k["ic95"] and k["detalle"] else ""), "celda"), _p(ic, "celda"),
            _p(_meta_txt(k), "celda"), _p(str(necesarias) if necesarias else "—", "celda"),
            _celda_estado(k["estado"])])
    t = _tabla(filas, [54 * mm, 32 * mm, 26 * mm, 26 * mm, 13 * mm, 29 * mm])
    _estilo_estados(t, [k["estado"] for k in kpis], 5)
    h.append(t)
    h.append(_p("n mín.: corridas sin fallos que hacen falta para que el IC 95 % garantice la meta "
                "(con 0 fallos, el extremo inferior es 0.025^(1/n)). En las metas de 100 % se exige 0 fallos y "
                "una garantía de 95 %.", "chico"))

    # --- Una sección por categoría
    h.append(PageBreak())
    h.append(_p("Resultados por categoría", "h2"))
    for categoria in dict.fromkeys(k["categoria"] for k in kpis):
        grupo = [k for k in kpis if k["categoria"] == categoria]
        bloque = [_p(categoria, "h3")]
        porcentuales = [k for k in grupo if k["unidad"] == "%"]
        if porcentuales and len(porcentuales) == len(grupo):
            bloque.append(grafico_barras([{"etiqueta": k["nombre"], "valor": k["valor"], "ic95": k["ic95"],
                                           "meta": k["meta"]} for k in porcentuales]))
        filas = [["KPI", "Valor", "Meta", "Estado", "Fuente de la meta"]]
        for k in grupo:
            filas.append([_p(k["nombre"], "celda"), _p(_fmt(k["valor"], k["unidad"]), "celda"),
                          _p(_meta_txt(k), "celda"), _celda_estado(k["estado"]), _p(k["fuente"], "chico")])
        t = _tabla(filas, [52 * mm, 24 * mm, 20 * mm, 28 * mm, 56 * mm])
        _estilo_estados(t, [k["estado"] for k in grupo], 3)
        bloque += [t, Spacer(1, 2 * mm)]
        h.append(KeepTogether(bloque))
    h.append(_leyenda_grafico())

    # --- Motor: 36 casos
    h.append(PageBreak())
    h.append(_p(f"Motor de cotización: {motor['ok']} de {motor['total']} casos correctos", "h2"))
    h.append(_p("Valores esperados calculados con un oráculo independiente en Decimal (redondeo comercial a "
                "2 decimales) y comparados al centavo con el motor, el texto de WhatsApp y la validación de "
                "argumentos del LLM.", "texto"))
    h.append(Spacer(1, 2 * mm))
    h.append(grafico_barras([{"etiqueta": f"{c} ({v['ok']}/{v['total']})", "valor": v["ok"] / v["total"]}
                             for c, v in motor["por_categoria"].items()], meta=1.0))
    h.append(_p("Barra morada: % de casos correctos de la categoría · marca naranja: meta (100 %).", "chico"))
    filas = [["ID", "Categoría", "Caso", "Resultado"]]
    estados = []
    for r in motor["resultados"]:
        estado = "Cumple" if r["ok"] else "No cumple"
        estados.append(estado)
        texto = "Correcto" if r["ok"] else "Falla: " + "; ".join(r["diferencias"][:2])
        filas.append([r["id"], _p(r["categoria"], "celda"), _p(r["descripcion"], "celda"), _p(texto, "celda")])
    t = _tabla(filas, [12 * mm, 42 * mm, 70 * mm, 56 * mm])
    _estilo_estados(t, estados, 3)
    h += [Spacer(1, 3 * mm), t]

    # --- Conversación por categoría de caso
    if evaluacion:
        h.append(PageBreak())
        h.append(_p("Evaluación conversacional por tipo de caso", "h2"))
        h.append(_p(f"Fuente: {os.path.basename(ruta_eval)} · éxito de tarea (pass^1) por categoría, "
                    "con IC 95 %. La meta global es ≥ 85 %.", "texto"))
        cats = por_categoria_eval(evaluacion)
        h.append(grafico_barras([{"etiqueta": f"{c['categoria']} ({c['ok']}/{c['n']})", "valor": c["valor"],
                                  "ic95": c["ic95"]} for c in cats], meta=0.85))
        h.append(_leyenda_grafico())
        fallas = [(id_caso, r) for id_caso, corridas in evaluacion["resultados"].items()
                  for r in corridas if not r["exito"]]
        if fallas:
            h.append(_p(f"Corridas con falla ({len(fallas)})", "h3"))
            filas = [["Caso", "Rep.", "Checks fallidos"]]
            for id_caso, r in fallas:
                malos = "; ".join(f"{c['check']}: {c['detalle']}" for c in r["checks"] if not c["ok"])
                filas.append([id_caso, str(r["repeticion"]), _p(malos[:300], "celda")])
            h.append(_tabla(filas, [24 * mm, 12 * mm, 144 * mm]))

    # --- Hallazgos y siguientes pasos
    h.append(_p("Lectura y siguientes pasos", "h2"))
    for linea in _hallazgos(kpis, motor, pruebas):
        h.append(_p("• " + linea, "texto"))
    h.append(Spacer(1, 3 * mm))
    h.append(_p("Las metas combinan evals de regresión (Anthropic, Demystifying evals for AI agents), BFCL y "
                "tau-bench para herramientas y éxito de tarea, guías de proveedores de chatbots (intención > 90 %, "
                "tarea > 85 %), OWASP Top 10 LLM para el alcance y los límites de respuesta de Nielsen (10 s). "
                "Donde no hay referencia, la meta es del equipo. Ningún número de la evaluación conversacional "
                "sale del set reservado: el set de desarrollo lo escribió Claude y sirve para ajustar.", "chico"))

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return ruta


def _hallazgos(kpis: List[Dict], motor: Dict, pruebas: Optional[Dict]) -> List[str]:
    lineas = []
    for r in motor["resultados"]:
        if not r["ok"]:
            lineas.append(f"Motor, caso {r['id']} ({r['descripcion']}): {'; '.join(r['diferencias'][:1])}.")
    for k in kpis:
        if k["estado"] == "No cumple":
            lineas.append(f"{k['nombre']}: {_fmt(k['valor'], k['unidad'])} frente a la meta {_meta_txt(k)}.")
    falta_n = [k["nombre"] for k in kpis if k["estado"] == "Cumple (falta n)"]
    if falta_n:
        detalle = ", ".join(f"{k['nombre'].split(' · ')[0]} necesita {corridas_necesarias(k)} corridas sin fallos"
                            for k in kpis if k["estado"] == "Cumple (falta n)" and corridas_necesarias(k))
        lineas.append(f"{len(falta_n)} KPIs alcanzan la meta pero necesitan más casos para garantizarla con el IC"
                      + (f" ({detalle})." if detalle else "."))
    sin = [k["nombre"] for k in kpis if k["estado"] == "Sin datos"]
    if sin:
        lineas.append("Sin datos todavía: " + ", ".join(sin) + " (se mide en la prueba de uso del 14/11).")
    return lineas


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval", default="", help="resultados_*.json de evaluar.py (por defecto, el último completo)")
    parser.add_argument("--sin-pytest", action="store_true")
    parser.add_argument("--salida", default=REPORTES)
    args = parser.parse_args()

    motor = verificar_todos()
    pruebas = None if args.sin_pytest else correr_pytest()
    ruta_eval = args.eval or ultima_evaluacion_completa()
    evaluacion = None
    if ruta_eval:
        with open(ruta_eval, encoding="utf-8") as f:
            evaluacion = json.load(f)
    kpis = construir_kpis(motor, pruebas, evaluacion)
    os.makedirs(args.salida, exist_ok=True)
    ruta = os.path.join(args.salida, f"resumen_kpis_{ahora().strftime('%Y%m%d_%H%M')}.pdf")
    generar_resumen_pdf(kpis, motor, pruebas, evaluacion, ruta_eval, ruta)
    for k in kpis:
        print(f"{k['estado']:<17} {k['nombre']}: {_fmt(k['valor'], k['unidad'])} (meta {_meta_txt(k)})")
    print(f"\nPDF: {ruta}")


if __name__ == "__main__":
    main()
