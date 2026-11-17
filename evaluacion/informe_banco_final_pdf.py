"""Informe final del banco de preguntas en PDF (lo genera evaluacion.py; también se puede rehacer a mano).

Uso:
    python evaluacion/informe_banco_final_pdf.py <carpeta de la corrida> [--oficial <corrida .jsonl>] [--salida x.pdf]

La carpeta trae resultado.json (KPI y metadatos). Si viene de varias corridas (meta.corridas), la tabla muestra
el resultado por corrida, el promedio y el rango. Con --oficial se agrega una columna de comparación con otra
corrida (opcional; evaluacion.py no la usa). Reutiliza el estilo de reporte_pdf.py (logo, colores, fuente Vera).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reporte_pdf import E, LOGO, ROJO, VERDE, _limpio, _pie, _tabla  # noqa: E402



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
    n_corridas = len(meta.get("corridas") or []) or 1

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
    ] if n_corridas == 1 else [
        ["Corridas", f"{n_corridas} corridas completas del banco ({meta['casos_banco']} casos cada una)"],
        ["Casos", f"{meta['ejecutados']}/{meta['total']} ejecutados · {meta['errores']} errores de ejecución"],
    ]
    ficha += [
        ["Juez", meta['modelo_juez']],
        ["Duración", f"{meta['duracion_min']} min"],
    ]
    h.append(_tabla([[_celda(a, negrita=True), _celda(b)] for a, b in ficha], [38 * mm, 130 * mm],
                    cabecera=False, zebra=False))

    if n_corridas > 1:
        h += [_p(f"Resultados: {cumplen} de {len(kpis)} indicadores cumplen su meta en el promedio de "
                 f"{n_corridas} corridas", "h2")]
        filas = [["Indicador", "Por corrida", "Promedio", "Mín–máx", "Meta", "Estado"]]
        for k in kpis:
            corridas = " · ".join("—" if v is None else f"{v:.1f}" for v in k["por_corrida"])
            rango = "—" if k.get("minimo") is None else f"{k['minimo']:.1f}–{k['maximo']:.1f} %"
            prom = "—" if k.get("porcentaje") is None else f"{k['porcentaje']:.1f} %"
            filas.append([_celda(k["indicador"], negrita=True), _celda(corridas), _celda(prom), _celda(rango),
                          _celda(f"{k['meta']} %"), _cumple(k)])
        h.append(_tabla(filas, [54 * mm, 36 * mm, 20 * mm, 24 * mm, 14 * mm, 20 * mm]))
        return _ejecucion(doc, h, meta, t, salida)
    h += [_p(f"Resultados: {cumplen} de {len(kpis)} indicadores cumplen su meta", "h2")]
    cab = ["Indicador", "Resultado", "IC 95 %", "Meta", "Estado"] + (["Prueba oficial"] if oficial else [])
    filas = [cab]
    por_nombre = {k["indicador"]: k for k in (oficial or [])}
    for k in kpis:
        ic = f"{k['ic95'][0]}–{k['ic95'][1]} %" if k.get("ic95") else "—"
        fila = [_celda(k["indicador"], negrita=True), _celda(_resultado(k)),
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
    if oficial:
        h.append(_p("La columna de la prueba oficial se colorea según si cumplía.", "chico"))

    return _ejecucion(doc, h, meta, t, salida)


def _ejecucion(doc, h, meta, t, salida):
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
