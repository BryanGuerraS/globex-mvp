"""Resumen en PDF de la corrida del lote nuevo (Globix v0, v1 y reglas), con el estilo de resumen_kpis.

Lee la carpeta que deja correr_lote_nuevo.py: 0_versiones.txt, la comparación
(comparacion_lote_nuevo_*.json) y los resultados de cada corrida (costo, latencia, fallas).
No llama a ningún LLM.

Uso:
    python evaluacion/resumen_lote_nuevo.py evaluacion/reportes/lote_nuevo_20261113
"""

import glob
import json
import os
import statistics
import sys
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from reportlab.graphics.shapes import Drawing, Line, Rect, String  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from database import ahora  # noqa: E402
from evaluacion.kpis_minimos import KPIS_MINIMOS, evaluar_estado  # noqa: E402
from evaluacion.reporte_pdf import BORDE, E, GRIS, LOGO, MORADO, NARANJA, _p, _tabla  # noqa: E402
from evaluacion.resumen_kpis import ESTADOS, _fmt, _meta_txt  # noqa: E402
from metricas import clopper_pearson  # noqa: E402

OPCIONES = ("v0", "v1", "reglas")
NOMBRES = {"v0": "Globix v0", "v1": "Globix v1", "reglas": "Reglas sin LLM"}
COLOR = {"v0": colors.HexColor("#A1A1AA"), "v1": MORADO, "reglas": colors.HexColor("#D4D4D8")}
TINTA = colors.HexColor("#27272A")
CUADRICULA = colors.HexColor("#E4E4E7")
BIGOTE = colors.HexColor("#52525B")
VERDE_FONDO, VERDE_TEXTO = colors.HexColor("#DCFCE7"), colors.HexColor("#166534")
AMBAR_FONDO, AMBAR_TEXTO = colors.HexColor("#FEF3C7"), colors.HexColor("#92400E")


def _pct(x: Optional[float], dec: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{dec}f} %"


def _pp(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:+.1f} pp".replace("-", "−")


def _rico(texto: str, estilo: str = "texto"):
    return Paragraph(texto, E[estilo])


def leer_carpeta(carpeta: str) -> Dict:
    versiones = {}
    with open(os.path.join(carpeta, "0_versiones.txt"), encoding="utf-8") as f:
        for linea in f:
            if "=" in linea:
                k, v = linea.strip().split("=", 1)
                versiones[k] = v
    ruta_comp = sorted(glob.glob(os.path.join(carpeta, "comparacion_lote_nuevo_*.json")))[-1]
    with open(ruta_comp, encoding="utf-8") as f:
        comparacion = json.load(f)
    corridas = {}
    for o in OPCIONES:
        corridas[o] = []
        for ruta in sorted(glob.glob(os.path.join(carpeta, o, "resultados_*.json"))):
            with open(ruta, encoding="utf-8") as f:
                corridas[o].append(json.load(f))
    return {"versiones": versiones, "comparacion": comparacion, "corridas": corridas}


def costo_latencia(corridas: List[Dict]) -> Dict:
    cl = [c["costo_latencia"] for c in corridas]
    def media(f):
        vals = [f(x) for x in cl if f(x) is not None]
        return statistics.mean(vals) if vals else None
    return {
        "costo_1000": media(lambda x: x.get("costo_por_1000_conversaciones_usd")),
        "p50": media(lambda x: (x.get("latencia_procesamiento") or {}).get("p50_ms")),
        "p95": media(lambda x: (x.get("latencia_procesamiento") or {}).get("p95_ms")),
        "llm": statistics.mean(x.get("llamadas_llm_promedio") or 0 for x in cl) if cl else None,
    }


def fallas_por_caso(corridas: List[Dict]) -> List[Dict]:
    """Casos que fallan en alguna corrida: en cuántas y qué checks."""
    por_caso: Dict[str, Dict] = {}
    for i, c in enumerate(corridas, 1):
        for cid, rs in c["resultados"].items():
            r = rs[0]
            if r["exito"]:
                continue
            d = por_caso.setdefault(cid, {"id": cid, "corridas": [], "checks": {}})
            d["corridas"].append(i)
            for ch in r["checks"]:
                if not ch["ok"]:
                    d["checks"].setdefault(ch["check"], ch["detalle"])
    return sorted(por_caso.values(), key=lambda d: (-len(d["corridas"]), d["id"]))


# Los KPIs del resumen del 06/11 que se pueden medir en el lote (sin motor, pruebas ni KPI de negocio)
CLAVES_SECUNDARIAS = [k["clave"] for k in KPIS_MINIMOS if k["clave"] not in ("V1_motor", "V2_pruebas", "kpi_atencion_60")]
DEBOUNCE_S = 5.0  # evaluar.py mide sin la espera de 5 s de agrupación de WhatsApp


def kpis_secundarios(corridas: List[Dict], con_llm: bool = True) -> List[Dict]:
    """Los KPIs de kpis_minimos.py sobre una opción: proporciones sumando corridas (como el resumen del
    06/11, que sumaba sus 3 repeticiones), pass^k sobre los casos y latencia/costo promedio."""
    medidos: Dict[str, tuple] = {}
    for clave in CLAVES_SECUNDARIAS:
        ks = [c["kpis"].get(clave) for c in corridas if c["kpis"].get(clave)]
        ok, n = sum(k["exitos"] for k in ks), sum(k["n"] for k in ks)
        if n:
            medidos[clave] = (ok / n, list(clopper_pearson(ok, n)), f"{ok}/{n}")
    if len(corridas) > 1:  # pass^k: el caso acierta en todas las corridas
        ids = set.intersection(*(set(c["resultados"]) for c in corridas))
        ok = sum(all(c["resultados"][i][0]["exito"] for c in corridas) for i in ids)
        medidos["consistencia_pass^3"] = (ok / len(ids), list(clopper_pearson(ok, len(ids))), f"{ok}/{len(ids)}")
    else:
        medidos.pop("consistencia_pass^3", None)
    cl = costo_latencia(corridas)
    if con_llm:  # las reglas no llaman al LLM: sin espera ni costo comparables
        esperas = [(c["costo_latencia"].get("latencia_total_cliente") or {}) for c in corridas]
        for p in ("p50", "p95"):
            vals = [e[f"{p}_ms"] for e in esperas if e.get(f"{p}_ms") is not None]
            if vals:
                medidos[f"espera_{p}_s"] = (statistics.mean(vals) / 1000 + DEBOUNCE_S, None, "incluye 5 s")
        medidos["costo_1000_usd"] = (cl["costo_1000"], None, "")
    filas = []
    for meta in KPIS_MINIMOS:
        if meta["clave"] not in CLAVES_SECUNDARIAS:
            continue
        valor, ic, detalle = medidos.get(meta["clave"], (None, None, ""))
        filas.append({**meta, "valor": valor, "ic95": ic, "detalle": detalle,
                      "estado": evaluar_estado(meta, valor, ic)})
    return filas


# ------------------------------------------------------------------ gráficos

def grafico_opciones(metricas: List[Dict], ancho: float = 180 * mm) -> Drawing:
    """Por métrica, una barra por opción (promedio) con bigote mín.–máx. entre corridas."""
    izq, der, arriba, abajo = 46 * mm, 18 * mm, 3 * mm, 9 * mm
    alto_barra, sep, sep_grupo = 4.2 * mm, 1.2 * mm, 5 * mm
    alto_grupo = len(OPCIONES) * (alto_barra + sep) + sep_grupo
    alto = arriba + abajo + alto_grupo * len(metricas)
    d = Drawing(ancho, alto)
    plot = ancho - izq - der

    def x(p):
        return izq + plot * max(0.0, min(1.0, p))

    for t in (0, 0.25, 0.5, 0.75, 1.0):
        d.add(Line(x(t), abajo, x(t), alto - arriba, strokeColor=CUADRICULA, strokeWidth=0.5))
        d.add(String(x(t), abajo - 4 * mm, f"{t * 100:.0f} %", fontName="Vera", fontSize=6.5,
                     fillColor=GRIS, textAnchor="middle"))
    for g, m in enumerate(metricas):
        y_top = alto - arriba - g * alto_grupo
        d.add(String(izq - 3 * mm, y_top - 3.2 * mm, m["titulo"], fontName="VeraBd", fontSize=7.5,
                     fillColor=TINTA, textAnchor="end"))
        d.add(String(izq - 3 * mm, y_top - 6.6 * mm, f"{m['n']} casos", fontName="Vera", fontSize=6.5,
                     fillColor=GRIS, textAnchor="end"))
        for i, o in enumerate(OPCIONES):
            s = m["opciones"][o]
            cy = y_top - i * (alto_barra + sep) - alto_barra / 2
            if s["promedio"] is None:
                continue
            d.add(Rect(x(0), cy - alto_barra / 2, max(0.5, x(s["promedio"]) - x(0)), alto_barra, rx=1, ry=1,
                       fillColor=COLOR[o], strokeColor=None))
            if s["minimo"] is not None and s["maximo"] is not None and s["maximo"] > s["minimo"]:
                d.add(Line(x(s["minimo"]), cy, x(s["maximo"]), cy, strokeColor=BIGOTE, strokeWidth=0.9))
                for e in (s["minimo"], s["maximo"]):
                    d.add(Line(x(e), cy - 1.1 * mm, x(e), cy + 1.1 * mm, strokeColor=BIGOTE, strokeWidth=0.9))
            d.add(String(x(1.0) + 2 * mm, cy - 2.2, f"{NOMBRES[o].replace('Globix ', '')} {_pct(s['promedio'])}",
                         fontName="VeraBd" if o == "v1" else "Vera", fontSize=7, fillColor=TINTA))
    return d


def grafico_diferencias(filas: List[Dict], ancho: float = 180 * mm, lim=(-0.35, 0.35)) -> Drawing:
    """Diferencias en pp con IC 95 % por bootstrap; línea en cero."""
    izq, der, arriba, abajo, alto_fila = 62 * mm, 22 * mm, 3 * mm, 9 * mm, 8 * mm
    alto = arriba + abajo + alto_fila * len(filas)
    d = Drawing(ancho, alto)
    plot = ancho - izq - der

    def x(v):
        return izq + plot * (max(lim[0], min(lim[1], v)) - lim[0]) / (lim[1] - lim[0])

    for t in (-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3):
        d.add(Line(x(t), abajo, x(t), alto - arriba, strokeColor=BIGOTE if t == 0 else CUADRICULA,
                   strokeWidth=0.9 if t == 0 else 0.5))
        d.add(String(x(t), abajo - 4 * mm, f"{t * 100:+.0f}".replace("+0", "0").replace("-", "−"),
                     fontName="Vera", fontSize=6.5, fillColor=GRIS, textAnchor="middle"))
    for i, f in enumerate(filas):
        cy = alto - arriba - alto_fila * (i + 0.5)
        d.add(String(izq - 3 * mm, cy - 2.2, f["etiqueta"], fontName="Vera", fontSize=7.5,
                     fillColor=TINTA, textAnchor="end"))
        li, ls = f["ic95"]
        significativa = li is not None and (li > 0 or ls < 0)
        color = MORADO if significativa else colors.HexColor("#A1A1AA")
        d.add(Line(x(li), cy, x(ls), cy, strokeColor=color, strokeWidth=1.4))
        for e in (li, ls):
            d.add(Line(x(e), cy - 1.3 * mm, x(e), cy + 1.3 * mm, strokeColor=color, strokeWidth=1.4))
        d.add(Rect(x(f["valor"]) - 1.3 * mm, cy - 1.3 * mm, 2.6 * mm, 2.6 * mm, fillColor=color, strokeColor=None))
        d.add(String(x(lim[1]) + 2 * mm, cy - 2.2, _pp(f["valor"]), fontName="VeraBd" if significativa else "Vera",
                     fontSize=7.5, fillColor=TINTA))
    return d


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(NARANJA)
    canvas.setLineWidth(2)
    canvas.line(15 * mm, 287 * mm, 195 * mm, 287 * mm)
    canvas.setFont("Vera", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(15 * mm, 10 * mm, "Globex Courier · Lote nuevo: Globix v0, v1 y reglas · Capstone UTEC")
    canvas.drawRightString(195 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()


# ------------------------------------------------------------------ PDF

LECTURA_FALLAS = {
    "GX-N-002": "Falla de medición: el cliente da el precio sin y con impuestos; la v1 usa USD 139.74 con sin_tax "
                "(misma boleta que USD 130 + TAX), el check espera USD 130. La referencia no se cambia tras ver respuestas.",
    "GX-N-014": "Falla real: con \"189 dólares el total con taxes\" el LLM arma mal la llamada a la herramienta tres "
                "veces y Globix responde con su mensaje de error (probable relación con los parámetros nuevos del TAX).",
    "GX-N-001": "Falla real: vuelve a pedir los datos en vez de cotizar con producto, precio y peso ya dados.",
}


def generar_pdf(datos: Dict, ruta: str) -> str:
    v, comp, corridas = datos["versiones"], datos["comparacion"], datos["corridas"]
    met = comp["metricas"]
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="Lote nuevo: Globix v0, v1 y reglas")
    h: List = []
    if os.path.exists(LOGO):
        h += [Image(LOGO, width=42 * mm, height=42 * mm * 0.3, kind="proportional", hAlign="LEFT"), Spacer(1, 4 * mm)]
    h.append(_p("Lote nuevo: Globix v0, v1 y reglas", "titulo"))
    n_casos = met["checks"]["n_casos"]
    h.append(_p(f"Generado el {ahora():%d/%m/%Y %H:%M} (hora de Lima). Corrida del {v.get('inicio', '—')}: "
                f"{n_casos} casos reales sellados, Globix v0 y v1 ×{v.get('repeticiones', '3')} y reglas ×1, "
                f"cada corrida calificada por el juez {v.get('modelo_juez', '—')}.", "chico"))
    h.append(Spacer(1, 5 * mm))

    # --- Tablero: atención correcta por opción
    juez = met.get("juez")
    principal = juez or met["checks"]
    celdas = [[_rico(f'<font color="#{(MORADO if o == "v1" else TINTA).hexval()[2:]}">'
                     f'{_pct(principal["opciones"][o]["promedio"])}</font>', "titulo") for o in OPCIONES],
              [_p(NOMBRES[o], "celda_neg") for o in OPCIONES]]
    tablero = Table(celdas, colWidths=[60 * mm] * 3)
    tablero.setStyle(TableStyle([("BOX", (i, 0), (i, 1), 0.6, BORDE) for i in range(3)]
                                + [("BACKGROUND", (1, 0), (1, 1), colors.HexColor("#F3F0F7")),
                                   ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    nombre_principal = "Atención correcta según el juez" if juez else "Éxito de tarea (checks)"
    h += [_p(f"{nombre_principal}: {principal['n_casos']} casos, promedio de las corridas", "h3"), tablero,
          Spacer(1, 3 * mm)]

    indebidas = comp["contrapeso"]["no_cotiza_indebidamente"]["opciones"]
    mejora = juez and juez["opciones"]["v1"]["promedio"] > juez["opciones"]["v0"]["promedio"]
    no_sube = indebidas["v1"]["promedio"] <= indebidas["v0"]["promedio"]
    d10 = juez["diferencias"]["v1 − v0"] if juez else met["checks"]["diferencias"]["v1 − v0"]
    concluyente = d10["ic95"][0] is not None and d10["ic95"][0] > 0
    decision = Table([[_rico(
        f"<b>Decisión pre-registrada: {'la v1 reemplaza a la v0' if mejora and no_sube else 'se mantiene la v0'}.</b> "
        f"La v1 {'sube' if mejora else 'no sube'} la atención correcta ({_pp(d10['diferencia'])}, IC 95 % "
        f"[{_pp(d10['ic95'][0])}, {_pp(d10['ic95'][1])}]) y {'no aumenta' if no_sube else 'aumenta'} las cotizaciones "
        f"indebidas ({indebidas['v1']['promedio']:.0f} frente a {indebidas['v0']['promedio']:.0f}). "
        + ("La mejora es concluyente." if concluyente else
           "La mejora sobre la v0 no es concluyente: el intervalo incluye el cero con 54 casos."), "texto")]],
        colWidths=[180 * mm])
    fondo, borde = (VERDE_FONDO, VERDE_TEXTO) if concluyente else (AMBAR_FONDO, AMBAR_TEXTO)
    decision.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fondo), ("BOX", (0, 0), (-1, -1), 0.8, borde),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    h += [decision, Spacer(1, 2 * mm)]

    # --- Métricas por opción
    h.append(_p("Métricas por opción", "h2"))
    orden = [k for k in ("juez", "checks", "k2") if k in met]
    titulos = {"juez": "Atención correcta (juez)", "checks": "Éxito de tarea (checks)", "k2": "K2 · precio y peso"}
    h.append(grafico_opciones([{"titulo": titulos[k], "n": met[k]["n_casos"], "opciones": met[k]["opciones"]}
                               for k in orden]))
    h.append(_p("Barra: promedio de las corridas · línea gris: mínimo y máximo entre corridas (las reglas son "
                "deterministas y corren una vez). Morado: la v1. IC 95 % de Clopper-Pearson por corrida.", "chico"))
    filas = [["Métrica", "Opción", "Promedio", "Mín.–máx.", "Corridas: aciertos/n [IC 95 %]"]]
    for k in orden:
        for o in OPCIONES:
            s = met[k]["opciones"][o]
            det = "; ".join(f"{t['exitos']}/{t['n']} [{_pct(t['ic95'][0], 0)}–{_pct(t['ic95'][1], 0)}]"
                            for t in s["corridas"])
            filas.append([_p(titulos[k] if o == "v0" else "", "celda"), _p(NOMBRES[o], "celda"),
                          _p(_pct(s["promedio"]), "celda_neg" if o == "v1" else "celda"),
                          _p(f"{_pct(s['minimo'])} – {_pct(s['maximo'])}" if o != "reglas" else "—", "celda"),
                          _p(det, "celda")])
    h.append(_tabla(filas, [36 * mm, 24 * mm, 18 * mm, 30 * mm, 72 * mm]))

    # --- Diferencias
    h.append(PageBreak())
    h.append(_p("Diferencias entre opciones", "h2"))
    h.append(_p("IC 95 % por bootstrap de casos (5 000 remuestreos, semilla 17). Con varias corridas, cada caso aporta "
                "su tasa media de acierto. En morado y negrita, las diferencias cuyo intervalo no incluye el cero.",
                "texto"))
    filas_d = []
    for k in orden:
        for nombre, dd in met[k]["diferencias"].items():
            filas_d.append({"etiqueta": f"{titulos[k].split(' (')[0].split(' ·')[0]}: {nombre}",
                            "valor": dd["diferencia"], "ic95": dd["ic95"]})
    h.append(grafico_diferencias(filas_d))
    h.append(_p("Eje: puntos porcentuales. Cuadrado: diferencia observada · línea: IC 95 %.", "chico"))
    filas = [["Métrica", "Comparación", "Diferencia", "IC 95 %", "Casos"]]
    for k in orden:
        for nombre, dd in met[k]["diferencias"].items():
            sig = dd["ic95"][0] is not None and (dd["ic95"][0] > 0 or dd["ic95"][1] < 0)
            filas.append([_p(titulos[k], "celda"), _p(nombre, "celda"),
                          _p(_pp(dd["diferencia"]), "celda_neg" if sig else "celda"),
                          _p(f"[{_pp(dd['ic95'][0])}, {_pp(dd['ic95'][1])}]", "celda"), _p(str(dd["n"]), "celda")])
    h.append(_tabla(filas, [44 * mm, 30 * mm, 26 * mm, 50 * mm, 30 * mm]))

    # --- Contrapeso
    h.append(_p("Contrapeso", "h2"))
    filas = [["Falla", *[NOMBRES[o] for o in OPCIONES], "Casos donde aplica"]]
    for c in comp["contrapeso"].values():
        filas.append([_p(c["nombre"], "celda")]
                     + [_p(f"{c['opciones'][o]['promedio']:.1f} ({c['opciones'][o]['minimo']}–{c['opciones'][o]['maximo']})"
                           if o != "reglas" else f"{c['opciones'][o]['promedio']:.0f}", "celda") for o in OPCIONES]
                     + [_p(str(c["opciones"]["v1"]["n"]), "celda")])
    h.append(_tabla(filas, [50 * mm, 30 * mm, 30 * mm, 30 * mm, 40 * mm]))
    h.append(_p("Promedio de fallas por corrida (mínimo–máximo). Cotización indebida: cotiza cuando el caso no lo "
                "permite. Derivación innecesaria: pasa a un asesor un caso que el bot debía atender.", "chico"))

    # --- Costo y latencia
    h.append(_p("Costo y latencia", "h2"))
    filas = [["Opción", "USD por 1 000 conversaciones", "Procesamiento p50", "Procesamiento p95", "Llamadas al LLM por turno"]]
    for o in ("v0", "v1"):
        cl = costo_latencia(corridas[o])
        filas.append([_p(NOMBRES[o], "celda"), _p(f"USD {cl['costo_1000']:.2f}" if cl["costo_1000"] is not None else "—", "celda"),
                      _p(f"{cl['p50'] / 1000:.1f} s" if cl["p50"] else "—", "celda"),
                      _p(f"{cl['p95'] / 1000:.1f} s" if cl["p95"] else "—", "celda"),
                      _p(f"{cl['llm']:.2f}" if cl["llm"] else "—", "celda")])
    h.append(_tabla(filas, [34 * mm, 44 * mm, 32 * mm, 32 * mm, 38 * mm]))
    h.append(_p("Promedio de las corridas, solo Globix (las reglas no llaman al LLM). El procesamiento no incluye los "
                "5 s de agrupación de mensajes de WhatsApp.", "chico"))

    # --- Análisis secundario: KPIs contra las metas mínimas
    h.append(PageBreak())
    h.append(_p("Análisis secundario: KPIs contra las metas mínimas", "h2"))
    h.append(_rico("<b>No pre-registrado.</b> Son los KPIs y las metas del resumen del 06/11 (set de desarrollo), "
                   "aplicados al lote para poder comparar los dos informes. La decisión entre versiones sale de la "
                   "página 1, no de esta tabla. Las proporciones suman las corridas, como en el informe del 06/11; "
                   "con pocos casos por tipo, la mayoría queda \"falta n\".", "texto"))
    h.append(Spacer(1, 2 * mm))
    tablas = {o: kpis_secundarios(corridas[o], con_llm=(o != "reglas")) for o in OPCIONES}
    filas = [["KPI", "Meta", *[NOMBRES[o] for o in OPCIONES]]]
    reglas_estilo = []
    for i, k in enumerate(tablas["v1"], start=1):
        fila = [_p(k["nombre"], "celda"), _p(_meta_txt(k), "celda")]
        for j, o in enumerate(OPCIONES, start=2):
            x = next(f for f in tablas[o] if f["clave"] == k["clave"])
            fondo, color = ESTADOS[x["estado"]]
            if x["valor"] is None:
                texto = "—"
            else:
                texto = _fmt(x["valor"], x["unidad"])
                if x["ic95"]:
                    texto += f" ({x['detalle']})<br/>IC {x['ic95'][0] * 100:.0f}–{x['ic95'][1] * 100:.0f} %"
            texto += f'<br/><font color="#{color.hexval()[2:]}"><b>{x["estado"]}</b></font>'
            fila.append(Paragraph(texto, E["celda"]))
            reglas_estilo.append(("BACKGROUND", (j, i), (j, i), fondo))
        filas.append(fila)
    t = _tabla(filas, [44 * mm, 25 * mm, 37 * mm, 37 * mm, 37 * mm], zebra=False)
    t.setStyle(TableStyle(reglas_estilo))
    h.append(t)
    h.append(_p("Cumple: el extremo desfavorable del IC 95 % alcanza la meta. Cumple (falta n): el valor alcanza la "
                "meta, pero el IC no lo garantiza. Sin datos: el lote no tiene casos de ese tipo (por ejemplo, fuera "
                "de alcance) o la opción no lo mide (las reglas no tienen espera ni costo de LLM, ni pass^3 con una "
                "corrida). K1 aquí es el tipo de respuesta correcto; en el lote hay solo 3 casos de mercancía "
                "restringida.", "chico"))

    # --- Fallas de la v1
    h.append(PageBreak())
    fallas = fallas_por_caso(corridas["v1"])
    h.append(_p(f"Casos que falla la v1 ({len(fallas)} de {n_casos})", "h2"))
    h.append(_p("Por checks automáticos, en cualquiera de las corridas. El lote ya se usó: estas fallas no se corrigen "
                "contra él, y un arreglo posterior debe medirse con casos nuevos.", "texto"))
    filas = [["Caso", "Corridas", "Checks fallidos y lectura"]]
    for f in fallas:
        malos = "; ".join(f"{k}: {d}" for k, d in f["checks"].items())[:260]
        texto = (f"<b>{LECTURA_FALLAS[f['id']]}</b><br/>" if f["id"] in LECTURA_FALLAS else "") + \
            malos.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        filas.append([_p(f["id"], "celda"), _p(f"{len(f['corridas'])} de {len(corridas['v1'])}", "celda"),
                      Paragraph(texto, E["celda"])])
    h.append(_tabla(filas, [22 * mm, 18 * mm, 140 * mm]))

    # --- Cómo se midió
    h.append(_p("Cómo se midió y límites", "h2"))
    lineas = [
        f"Lote: {n_casos} casos reales de leads distintos, ninguno en el banco v3, sellado hasta congelar la v1. "
        f"SHA-256 {v.get('lote_sha256', '—')[:16]}…, verificado antes de correr.",
        f"Código: v0 = commit {v.get('v0', '—')[:7]}, v1 = commit {v.get('v1', '—')[:7]}; herramientas de evaluación "
        f"del commit {v.get('herramientas', '—')[:7]}, las mismas para las tres opciones.",
        "Reglas fijadas antes de ver respuestas en docs/prerregistro_lote_nuevo.md: checks sobre los 60 casos, juez "
        "solo sobre los 54 con referencia \"Listo\", K2 sobre los 15 de cotización, una sola ejecución por opción.",
        "El juez es reproducible en el procedimiento (temperatura 0, rúbrica y prompt versionados; κ = 0.93 entre "
        "dos pasadas en el set de desarrollo), no al bit: Groq no acepta semilla. Aún no está validado contra un "
        "revisor humano.",
        "La v0 conserva sus reglas de precio (tope USD 1 200, 22.72 % sobre CIF); el baseline usa el código de la v1.",
        "Con 54–60 casos los intervalos son anchos (±12 pp cerca de 50 %); el lote es estratificado y no estima "
        "prevalencias de los 7 037 leads.",
    ]
    for linea in lineas:
        h.append(_p("• " + linea, "texto"))

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return ruta


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit(__doc__)
    carpeta = os.path.abspath(argv[0])
    datos = leer_carpeta(carpeta)
    ruta = os.path.join(carpeta, f"resumen_lote_nuevo_{ahora():%Y%m%d_%H%M}.pdf")
    print(generar_pdf(datos, ruta))


if __name__ == "__main__":
    main()
