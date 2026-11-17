"""Informe final del banco de preguntas en PDF, a partir de lo que descarga enviar_banco_final.py.

Uso:
    python evaluacion/informe_banco_final_pdf.py <carpeta del trabajo> [--oficial <corrida 5b2fadc>] [--salida x.pdf]

La carpeta del trabajo trae resultado.json (KPI y metadatos), casos.jsonl y juez.jsonl. Con --oficial se
agrega la columna de la prueba oficial (versión congelada) para comparar. Reutiliza el estilo de
reporte_pdf.py (logo, colores de Globex, fuente Vera).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reporte_pdf import E, LOGO, MORADO, NARANJA, ROJO, VERDE, _limpio, _pie, _tabla  # noqa: E402

# Nombres finales de los indicadores (acordados con el equipo): se usan completos en todo el informe
CORTO = {}


def _p(texto, estilo="texto"):
    return Paragraph(_limpio(texto), E[estilo])


def _celda(texto, color=None, negrita=False):
    estilo = "celda_neg" if negrita else "celda"
    t = _limpio(texto)
    return Paragraph(f'<font color="{color}">{t}</font>' if color else t, E[estilo])


def _resultado(k: Dict) -> str:
    if k.get("porcentaje") is None:
        return "—"
    if k.get("aciertos") is not None and k.get("casos"):
        return f"{k['aciertos']}/{k['casos']} = {k['porcentaje']:.1f} %"
    return f"{k['porcentaje']:.1f} %" + (f" (prom. de {k['casos']} chats)" if k.get("casos") else "")


def _cumple(k: Dict):
    return _celda("Cumple" if k["cumple"] else "No cumple", VERDE.hexval() if k["cumple"] else ROJO.hexval(), True)


def _notas_juez(juez: List[Dict]) -> Dict[str, str]:
    """Por caso no aprobado, las notas del juez en una línea (sin repetir la pregunta del banco)."""
    notas = {}
    for f in juez:
        v = f.get("veredicto") or {}
        if f.get("banco") == "CHATS_COMPARTIDOS":
            s = ((v.get("resumen") or {}).get("casos") or [{}])[0]
            bajos = [f"{c} {s[c].get('nota')}" for c in ("C1", "C2", "C3", "C4")
                     if isinstance(s.get(c), dict) and (s[c].get("nota") or 5) < 4]
            notas[f["id"]] = "resumen: " + (", ".join(bajos) or f"nota {s.get('nota_promedio')}")
        else:
            c = (v.get("casos") or [{}])[0]
            criterios = {k: x.get("nota") for k, x in (c.get("criterios") or {}).items() if isinstance(x, dict)}
            faltan = sum(1 for r in (c.get("requisitos") or []) if r.get("estado") != "COMUNICADO")
            partes = [" ".join(f"{k} {n}" for k, n in criterios.items() if n is not None)]
            if faltan:
                partes.append(f"{faltan} requisito(s) no comunicado(s)")
            if c.get("avance_indebido_a_cotizacion"):
                partes.append("avance indebido a cotización")
            if c.get("errores_criticos"):
                partes.append("error crítico")
            notas[f["id"]] = "; ".join(p for p in partes if p)
    return notas


def kpis_oficiales(corrida: Path, carpeta_banco: Path) -> Optional[List[Dict]]:
    """KPI de una corrida guardada localmente (revisión + juez) con el mismo cálculo del endpoint."""
    import banco_final
    revision = corrida.with_suffix(".revision.json")
    juez = corrida.with_name(f"JUEZ-{corrida.stem}.resumen.json")
    if not (revision.exists() and juez.exists()):
        return None
    filas = [json.loads(l) for l in corrida.read_text(encoding="utf-8").splitlines() if l.strip()]
    indice = json.loads((carpeta_banco / "00_Indice_Bancos.txt").read_text(encoding="utf-8"))
    return banco_final.calcular_kpis(filas, json.loads(revision.read_text(encoding="utf-8")),
                                     json.loads(juez.read_text(encoding="utf-8")), indice)


def generar(trabajo: Path, salida: Path, oficial: Optional[List[Dict]] = None, commit_oficial: str = "5b2fadc"):
    resultado = json.loads((trabajo / "resultado.json").read_text(encoding="utf-8"))
    meta, kpis, t = resultado["meta"], resultado["kpis"], resultado.get("tiempos") or {}
    cumplen = sum(1 for k in kpis if k["cumple"])

    doc = SimpleDocTemplate(str(salida), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="Informe final del banco de preguntas",
                            author="Equipo 1 · Capstone UTEC")
    h = []
    if Path(LOGO).exists():
        h += [Image(LOGO, width=38 * mm, height=38 * mm * 0.32, kind="proportional", hAlign="LEFT"), Spacer(1, 4)]
    h += [_p("Informe final del banco de preguntas", "titulo"),
          _p(f"Globix, chatbot de primera atención comercial · Generado el {meta['generado']} (hora de Lima)", "chico"),
          Spacer(1, 8)]
    ficha = [
        ["Casos", f"{meta['ejecutados']}/{meta['total']} ejecutados · {meta['errores']} errores de ejecución"],
        ["Juez", meta['modelo_juez']],
        ["Duración", f"{meta['duracion_min']} min"],
    ]
    h.append(_tabla([[_celda(a, negrita=True), _celda(b)] for a, b in ficha], [38 * mm, 130 * mm],
                    cabecera=False, zebra=False))

    h += [_p(f"Resultados: {cumplen} de {len(kpis)} indicadores cumplen su meta", "h2")]
    cab = ["Indicador", "Resultado", "IC 95 %", "Meta", "Estado"] + (["Prueba oficial"] if oficial else [])
    filas = [cab]
    por_nombre = {k["indicador"]: k for k in (oficial or [])}
    for k in kpis:
        ic = f"{k['ic95'][0]}–{k['ic95'][1]} %" if k.get("ic95") else "—"
        fila = [_celda(CORTO.get(k["indicador"], k["indicador"]), negrita=True), _celda(_resultado(k)),
                _celda(ic), _celda(f"{k['meta']} %"), _cumple(k)]
        if oficial:
            o = por_nombre.get(k["indicador"])
            fila.append(_celda(f"{o['porcentaje']:.1f} %" if o and o.get("porcentaje") is not None else "—",
                               VERDE.hexval() if o and o["cumple"] else ROJO.hexval()))
        filas.append(fila)
    anchos = ([52 * mm, 36 * mm, 24 * mm, 13 * mm, 20 * mm, 22 * mm] if oficial
              else [62 * mm, 40 * mm, 28 * mm, 16 * mm, 22 * mm])
    h.append(_tabla(filas, anchos))
    h.append(Spacer(1, 4))
    h.append(_p("Calidad de respuesta sobre productos con condiciones especiales cumple solo si alcanza la meta y no hay avances indebidos a cotización. "
                + ("La columna de la prueba oficial se colorea según si cumplía." if oficial else ""), "chico"))

    h += [_p("Ejecución", "h2")]
    filas = [["Dato", "Valor"],
             ["Casos ejecutados", f"{meta['ejecutados']} de {meta['total']}"],
             ["Errores de ejecución", str(meta["errores"])],
             ["Errores del juez", str(len(meta.get("errores_del_juez") or []))]]
    if t:
        filas += [["Tiempo por turno (p50 / p95)", f"{t['p50_s']} s / {t['p95_s']} s ({t['turnos']} turnos)"]]
    # La cabecera va en blanco sobre el morado, como en la tabla de resultados
    h.append(_tabla([[_celda(a, "#FFFFFF" if i == 0 else None, negrita=i == 0),
                      _celda(b, "#FFFFFF" if i == 0 else None, negrita=i == 0)] for i, (a, b) in enumerate(filas)],
                    [62 * mm, 106 * mm]))
    h.append(_p("El tiempo por turno no incluye los 5 s de agrupación de mensajes de WhatsApp.", "chico"))

    # Al final del informe (decisión del usuario 16/11): el banco ya se usó para corregir errores
    h += [Spacer(1, 10), _p("Este banco ya se había usado para identificar y corregir errores de Globix, por lo que "
                           "esta corrida no es una prueba independiente de generalización.", "chico")]
    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return salida


def main():
    p = argparse.ArgumentParser()
    p.add_argument("trabajo")
    p.add_argument("--oficial", help="corrida .jsonl de la prueba oficial (con su .revision.json y JUEZ-*.resumen.json)")
    p.add_argument("--banco", default=str(RAIZ / "Globex_Bancos_Prompts_Compactos_V2_1_20261115" / "Globex_Bancos_V2"))
    p.add_argument("--salida")
    a = p.parse_args()
    trabajo = Path(a.trabajo)
    oficial = kpis_oficiales(Path(a.oficial), Path(a.banco)) if a.oficial else None
    salida = Path(a.salida) if a.salida else trabajo / f"Informe_final_banco_{trabajo.name}.pdf"
    print(generar(trabajo, salida, oficial))


if __name__ == "__main__":
    main()
