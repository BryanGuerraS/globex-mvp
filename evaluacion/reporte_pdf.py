"""Reporte de evaluación de Globix en PDF (reportlab, ya es dependencia del proyecto).

Contiene: portada con logo y datos de la corrida, KPIs con IC 95 % de
Clopper-Pearson, costo y latencia, resultado por caso y el detalle de cada
falla con la conversación, herramientas, tokens y tiempos.
"""

import json
import os
import re
from typing import Dict, List

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(REPO, "assets", "logo_globex.png")
MORADO = colors.HexColor("#2E1A47")
NARANJA = colors.HexColor("#FF6900")
GRIS = colors.HexColor("#71717A")
BORDE = colors.HexColor("#E4E4E7")
FONDO = colors.HexColor("#F4F4F5")
VERDE = colors.HexColor("#15803D")
ROJO = colors.HexColor("#B91C1C")

_fuentes = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
pdfmetrics.registerFont(TTFont("Vera", os.path.join(_fuentes, "Vera.ttf")))
pdfmetrics.registerFont(TTFont("VeraBd", os.path.join(_fuentes, "VeraBd.ttf")))

_base = getSampleStyleSheet()
E = {
    "titulo": ParagraphStyle("t", parent=_base["Title"], fontName="VeraBd", fontSize=20, textColor=MORADO,
                             alignment=TA_LEFT, spaceAfter=4),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="VeraBd", fontSize=13, textColor=MORADO,
                         spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", parent=_base["Heading3"], fontName="VeraBd", fontSize=10.5, textColor=MORADO,
                         spaceBefore=10, spaceAfter=4),
    "texto": ParagraphStyle("p", parent=_base["BodyText"], fontName="Vera", fontSize=9, leading=12.5),
    "chico": ParagraphStyle("c", parent=_base["BodyText"], fontName="Vera", fontSize=8, leading=11, textColor=GRIS),
    "celda": ParagraphStyle("ce", parent=_base["BodyText"], fontName="Vera", fontSize=8, leading=10.5),
    "celda_neg": ParagraphStyle("cn", parent=_base["BodyText"], fontName="VeraBd", fontSize=8, leading=10.5),
}

NOMBRES_KPI = {
    "exito_tarea_pass1": "Éxito de tarea (pass^1)",
    "K1_exactitud_herramienta": "K1 · Exactitud de herramienta",
    "K2_exactitud_argumentos": "K2 · Exactitud de argumentos",
    "K3_sin_cotizacion_indebida": "K3 · Sin cotización indebida",
    "K4_derivacion_recall": "K4 · Derivación cuando corresponde",
    "K4_sin_derivacion_innecesaria": "K4 · Sin derivación innecesaria",
    "K5_guardrail": "K5 · Guardrail de mercancía",
    "K11_adherencia_alcance": "K11 · Adherencia al alcance",
}


def _limpio(texto) -> str:
    """Quita emojis y símbolos que la fuente no tiene, y escapa para reportlab."""
    texto = str(texto if texto is not None else "")
    texto = "".join(c for c in texto if ord(c) < 0x2000 or c in "–—…•·×≤≥→")
    texto = re.sub(r"[ \t]+", " ", texto)
    return escape(texto).replace("\n", "<br/>")


def _p(texto, estilo="texto"):
    return Paragraph(_limpio(texto), E[estilo])


def _pct(p: Dict) -> str:
    if not p.get("n"):
        return "—"
    li, ls = p["ic95"]
    return f"{p['valor'] * 100:.1f} %"


def _ic(p: Dict) -> str:
    if not p.get("n"):
        return "—"
    li, ls = p["ic95"]
    return f"[{li * 100:.1f} %, {ls * 100:.1f} %]"


def _seg(ms) -> str:
    return f"{ms / 1000:.2f} s" if ms is not None else "—"


def _tabla(filas: List[List], anchos, cabecera=True, zebra=True) -> Table:
    t = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0)
    estilo = [
        ("FONTNAME", (0, 0), (-1, -1), "Vera"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if cabecera:
        estilo += [
            ("BACKGROUND", (0, 0), (-1, 0), MORADO),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "VeraBd"),
        ]
    if zebra:
        for i in range(1 if cabecera else 0, len(filas)):
            if i % 2 == 0:
                estilo.append(("BACKGROUND", (0, i), (-1, i), FONDO))
    t.setStyle(TableStyle(estilo))
    return t


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(NARANJA)
    canvas.setLineWidth(2)
    canvas.line(15 * mm, 287 * mm, 195 * mm, 287 * mm)
    canvas.setFont("Vera", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(15 * mm, 10 * mm, "Globex Courier · Evaluación de Globix · Capstone UTEC")
    canvas.drawRightString(195 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()


def generar_reporte_pdf(meta: Dict, casos: List[Dict], resultados: Dict[str, List[Dict]], kpis: Dict,
                        resumen_costo: Dict, ruta: str, debounce_s: float = 5.0) -> str:
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Reporte de evaluación de Globix", author="Equipo Globex · UTEC")
    h: List = []

    # Portada / encabezado
    cabecera = []
    if os.path.exists(LOGO):
        cabecera.append(Image(LOGO, width=28 * mm, height=28 * mm * 778 / 879))
    cabecera.append([
        Paragraph("Reporte de evaluación de Globix", E["titulo"]),
        _p(f"{meta['fecha']} · modelo {meta['modelo']} · temperatura 0.2", "chico"),
        _p(f"Casos: {meta['archivo_casos']} ({len(casos)} casos × {meta['repeticiones']} repeticiones) · "
           f"duración {meta['duracion_s']:.0f} s", "chico"),
    ])
    t = Table([cabecera], colWidths=[34 * mm, None] if len(cabecera) == 2 else [None])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    h += [t, Spacer(1, 6)]

    exitosos = sum(r["exito"] for rs in resultados.values() for r in rs)
    total = sum(len(rs) for rs in resultados.values())
    fallas = total - exitosos
    h.append(_p(
        f"Se ejecutaron {total} conversaciones simuladas contra el flujo real de Globix (LLM real, sin WhatsApp). "
        f"{exitosos} cumplieron todo lo esperado y {fallas} tuvieron al menos una verificación fallida. "
        "Cada proporción se reporta con su intervalo de confianza de 95 % de Clopper-Pearson: con pocos casos, "
        "el intervalo es el dato que importa."))

    # KPIs
    h.append(Paragraph("Indicadores de calidad", E["h2"]))
    filas = [["Indicador", "Resultado", "Aciertos", "IC 95 %"]]
    for clave, p in kpis.items():
        nombre = NOMBRES_KPI.get(clave, clave.replace("consistencia_pass^", "Consistencia pass^"))
        filas.append([_p(nombre, "celda"), _p(_pct(p), "celda_neg"),
                      _p(f"{p['exitos']}/{p['n']}" if p.get("n") else "—", "celda"), _p(_ic(p), "celda")])
    h.append(_tabla(filas, [78 * mm, 28 * mm, 26 * mm, 48 * mm]))

    # Costo y latencia
    h.append(Paragraph("Costo y latencia", E["h2"]))
    if resumen_costo.get("turnos"):
        lat = resumen_costo["latencia_procesamiento"]
        filas = [
            ["Métrica", "Valor"],
            ["Turnos / conversaciones", f"{resumen_costo['turnos']} / {resumen_costo['conversaciones']}"],
            ["Llamadas al LLM por turno (promedio)", f"{resumen_costo['llamadas_llm_promedio']:.2f}"],
            ["Tokens por turno (entrada + salida)",
             f"{resumen_costo['tokens_entrada_promedio']:.0f} + {resumen_costo['tokens_salida_promedio']:.0f}"],
            ["Latencia del LLM (p50 · p95)",
             f"{_seg(resumen_costo['latencia_llm']['p50_ms'])} · {_seg(resumen_costo['latencia_llm']['p95_ms'])}"],
            ["Procesamiento por turno (p50 · p95)", f"{_seg(lat['p50_ms'])} · {_seg(lat['p95_ms'])}"],
        ]
        if lat["p50_ms"] is not None:
            filas.append([f"Espera estimada del cliente (+{debounce_s:.0f} s de agrupación)",
                          f"{_seg(lat['p50_ms'] + debounce_s * 1000)} · {_seg(lat['p95_ms'] + debounce_s * 1000)}"])
        filas += [
            ["Costo total de la evaluación", f"US$ {resumen_costo['costo_total_usd']:.4f}"],
            ["Costo por conversación", f"US$ {resumen_costo['costo_por_conversacion_usd']:.5f}"],
            ["Costo por 1 000 conversaciones", f"US$ {resumen_costo['costo_por_1000_conversaciones_usd']:.2f}"],
        ]
        h.append(_tabla(filas, [110 * mm, 70 * mm]))
        tipos = ", ".join(f"{k}: {v}" for k, v in resumen_costo["tipos_respuesta"].items())
        h.append(Spacer(1, 4))
        h.append(_p(f"Tipos de respuesta: {tipos}", "chico"))

    # Resultado por caso
    h.append(Paragraph("Resultado por caso", E["h2"]))
    reps = meta["repeticiones"]
    filas = [["Caso", "Categoría"] + [f"r{i}" for i in range(1, reps + 1)] + ["Verificaciones fallidas"]]
    estilos_celdas = []
    for i, caso in enumerate(casos, 1):
        rs = resultados.get(caso["id"], [])
        fallidos = sorted({c["check"] for r in rs for c in r["checks"] if not c["ok"]})
        fila = [caso["id"], caso.get("categoria", "")]
        for j, r in enumerate(rs):
            fila.append("OK" if r["exito"] else "Falla")
            estilos_celdas.append(("TEXTCOLOR", (2 + j, i), (2 + j, i), VERDE if r["exito"] else ROJO))
            estilos_celdas.append(("FONTNAME", (2 + j, i), (2 + j, i), "VeraBd"))
        fila.append(_p(", ".join(fallidos) or "—", "celda"))
        filas.append(fila)
    anchos = [20 * mm, 30 * mm] + [13 * mm] * reps + [None]
    t = _tabla(filas, anchos)
    t.setStyle(TableStyle(estilos_celdas))
    h.append(t)

    # Detalle de fallas
    fallas_det = [(c, r) for c in casos for r in resultados.get(c["id"], []) if not r["exito"]]
    h.append(PageBreak())
    h.append(Paragraph(f"Detalle de fallas ({len(fallas_det)})", E["h2"]))
    if not fallas_det:
        h.append(_p("Sin fallas."))
    for caso, r in fallas_det:
        bloque = [Paragraph(_limpio(f"{caso['id']} · r{r['repeticion']} — {caso.get('descripcion', '')}"), E["h3"])]
        bloque.append(_p(f"Esperado: {json.dumps(caso.get('esperado', {}), ensure_ascii=False)}", "chico"))
        for c in r["checks"]:
            if not c["ok"]:
                bloque.append(_p(f"✗ {c['check']} — {c['detalle']}".replace("✗", "Falla:"), "texto"))
        filas = []
        for n, turno in enumerate(r["turnos"], 1):
            filas.append([_p(f"Cliente {n}", "celda_neg"), _p(turno["cliente"], "celda")])
            if turno.get("silenciado"):
                filas.append([_p("Bot", "celda_neg"), _p("(silenciado: el mensaje queda para el asesor)", "celda")])
                continue
            meta_turno = (f"tipo: {turno.get('tipo_respuesta')} · LLM x{turno.get('llamadas_llm')} · "
                          f"{turno.get('tokens_entrada')}+{turno.get('tokens_salida')} tokens · "
                          f"LLM {_seg(turno.get('latencia_llm_ms'))}")
            herramientas = "<br/>".join(
                _limpio(f"{x['nombre']}({x.get('argumentos', '')}) → {json.dumps(x.get('resultado'), ensure_ascii=False)}")
                for x in turno.get("herramientas", []))
            respuestas = "<br/><br/>".join(_limpio(x) for x in turno.get("respuestas", [])) or "—"
            contenido = f"<font color='#71717A'>{_limpio(meta_turno)}</font>"
            if herramientas:
                contenido += f"<br/><font color='#5B3A8C'>{herramientas}</font>"
            contenido += f"<br/>{respuestas}"
            filas.append([_p("Globix", "celda_neg"), Paragraph(contenido, E["celda"])])
        t = Table(filas, colWidths=[22 * mm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDE),
            ("BACKGROUND", (0, 0), (0, -1), FONDO),
        ]))
        bloque.append(Spacer(1, 3))
        bloque.append(t)
        h.append(KeepTogether(bloque) if len(filas) <= 6 else bloque[0])
        if len(filas) > 6:
            h += bloque[1:]

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return ruta
