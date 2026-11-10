"""Compara dos corridas de evaluar.py sobre los mismos casos (modelo v0 contra baseline).

Las variantes de un caso real repiten la misma consulta, así que no son independientes:
los intervalos de la diferencia se calculan con bootstrap por GRUPO (caso real + sus
variantes), además del IC de Clopper-Pearson por corrida. También desglosa el éxito por
segmento (etiqueta esperada, categoría del banco y procedencia).

Uso:
    python evaluacion/comparar_resultados.py --casos evaluacion/reservado/casos_reservados.json \\
        --v0 evaluacion/reportes/resultados_X.json --baseline evaluacion/reportes/baseline_reglas/resultados_Y.json
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from metricas import clopper_pearson  # noqa: E402

KPIS = [
    ("exito_tarea_pass1", "Éxito de tarea (pass^1)"),
    ("K1_exactitud_herramienta", "K1 Tipo de respuesta correcto"),
    ("K3_sin_cotizacion_indebida", "K3 Sin cotización indebida"),
    ("K4_derivacion_recall", "K4 Deriva cuando corresponde"),
    ("K4_sin_derivacion_innecesaria", "K4 Sin derivación innecesaria"),
    ("K5_guardrail", "K5 Mercancía restringida"),
    ("K11_adherencia_alcance", "K11 Alcance"),
]


def exito_por_caso(resultados: Dict) -> Dict[str, bool]:
    return {cid: bool(rs[0]["exito"]) for cid, rs in resultados.items() if rs}


def bootstrap_diferencia(a: Dict[str, bool], b: Dict[str, bool], grupo: Dict[str, str],
                         repeticiones: int = 5000, semilla: int = 17) -> Tuple[float, float, float]:
    """Diferencia de éxito (a - b) con IC 95 % remuestreando grupos completos."""
    ids = sorted(set(a) & set(b))
    por_grupo = defaultdict(list)
    for i in ids:
        por_grupo[grupo.get(i, i)].append(i)
    grupos = sorted(por_grupo)
    dif = (sum(a[i] for i in ids) - sum(b[i] for i in ids)) / len(ids)
    azar = random.Random(semilla)
    valores = []
    for _ in range(repeticiones):
        muestra = [i for g in (azar.choice(grupos) for _ in grupos) for i in por_grupo[g]]
        valores.append((sum(a[i] for i in muestra) - sum(b[i] for i in muestra)) / len(muestra))
    valores.sort()
    return dif, valores[int(0.025 * repeticiones)], valores[int(0.975 * repeticiones)]


def ic_agrupado(a: Dict[str, bool], grupo: Dict[str, str], repeticiones: int = 5000,
                semilla: int = 19) -> Tuple[float, float]:
    """IC 95 % de una proporción remuestreando grupos (más ancho que Clopper-Pearson si hay variantes)."""
    por_grupo = defaultdict(list)
    for i in a:
        por_grupo[grupo.get(i, i)].append(i)
    grupos = sorted(por_grupo)
    azar = random.Random(semilla)
    valores = []
    for _ in range(repeticiones):
        muestra = [i for g in (azar.choice(grupos) for _ in grupos) for i in por_grupo[g]]
        valores.append(sum(a[i] for i in muestra) / len(muestra))
    valores.sort()
    return valores[int(0.025 * repeticiones)], valores[int(0.975 * repeticiones)]


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _celda(k: int, n: int) -> str:
    if not n:
        return "—"
    li, ls = clopper_pearson(k, n)
    return f"{_pct(k / n)} ({k}/{n}) [{_pct(li)}, {_pct(ls)}]"


def por_segmento(casos: List[Dict], exitos: Dict[str, Dict[str, bool]], clave) -> List[Tuple]:
    grupos = defaultdict(list)
    for c in casos:
        grupos[clave(c)].append(c["id"])
    filas = []
    for seg, ids in grupos.items():
        fila = [seg, len(ids)]
        for nombre in exitos:
            e = exitos[nombre]
            fila.append((sum(e.get(i, False) for i in ids), len(ids)))
        filas.append(tuple(fila))
    return sorted(filas, key=lambda f: -f[1])


def comparar(casos: List[Dict], v0: Dict, base: Dict, nombre_v0: str = "Globix (LLM)",
             nombre_base: str = "Reglas sin LLM") -> str:
    ids = {c["id"] for c in casos}
    e_v0 = {k: v for k, v in exito_por_caso(v0["resultados"]).items() if k in ids}
    e_b = {k: v for k, v in exito_por_caso(base["resultados"]).items() if k in ids}
    grupo = {c["id"]: c.get("banco", {}).get("grupo", c["id"]) for c in casos}
    n_grupos = len({grupo[i] for i in e_v0})
    dif, li, ls = bootstrap_diferencia(e_v0, e_b, grupo)
    L = [f"# Globix contra baseline de reglas · {datetime.now():%d/%m/%Y %H:%M}", "",
         f"Casos: {len(e_v0)} ({n_grupos} grupos: caso real + sus variantes). Una repetición por caso.", "",
         "## Métrica principal: éxito de tarea", "",
         "| Opción | Éxito | IC 95 % Clopper-Pearson | IC 95 % agrupado (bootstrap) | Costo por 1 000 conversaciones | Espera p50 / p95 |",
         "| --- | --- | --- | --- | --- | --- |"]
    for nombre, e, datos in ((nombre_v0, e_v0, v0), (nombre_base, e_b, base)):
        k, n = sum(e.values()), len(e)
        cl, cu = clopper_pearson(k, n)
        gl, gu = ic_agrupado(e, grupo)
        cost = datos.get("costo_latencia", {})
        espera = cost.get("latencia_total_cliente", {})
        p50 = espera.get("p50_ms")
        p95 = espera.get("p95_ms")
        L.append(f"| {nombre} | {_pct(k / n)} ({k}/{n}) | [{_pct(cl)}, {_pct(cu)}] | [{_pct(gl)}, {_pct(gu)}] | "
                 f"USD {cost.get('costo_por_1000_conversaciones_usd', 0):.2f} | "
                 f"{(p50 or 0) / 1000:.1f} s / {(p95 or 0) / 1000:.1f} s (sin los 5 s de agrupación) |")
    L += ["", f"**Diferencia (Globix − reglas): {dif * 100:+.1f} puntos, IC 95 % agrupado [{li * 100:+.1f}, {ls * 100:+.1f}].** "
          + ("El intervalo no incluye el 0: la diferencia es mayor que el rango." if li > 0 or ls < 0
             else "El intervalo incluye el 0: no se puede afirmar una diferencia."), "",
          "## KPIs", "", f"| KPI | {nombre_v0} | {nombre_base} |", "| --- | --- | --- |"]
    for clave, nombre in KPIS:
        a, b = v0["kpis"].get(clave), base["kpis"].get(clave)
        fa = _celda(a["exitos"], a["n"]) if a else "—"
        fb = _celda(b["exitos"], b["n"]) if b else "—"
        L.append(f"| {nombre} | {fa} | {fb} |")
    exitos = {nombre_v0: e_v0, nombre_base: e_b}
    for titulo, clave in (
        ("Por etiqueta esperada (Resultado Globix)", lambda c: c.get("banco", {}).get("resultado_globix", c["categoria"])),
        ("Por procedencia", lambda c: c.get("banco", {}).get("procedencia", "—")),
        ("Por categoría del banco", lambda c: c.get("banco", {}).get("segmento", "—")),
    ):
        L += ["", f"## {titulo}", "", f"| Segmento | n | {nombre_v0} | {nombre_base} | Diferencia |",
              "| --- | --: | --- | --- | --: |"]
        for seg, n, (ka, na), (kb, nb) in por_segmento(casos, exitos, clave):
            L.append(f"| {seg} | {n} | {_celda(ka, na)} | {_celda(kb, nb)} | {(ka / na - kb / nb) * 100:+.0f} pp |")
    return "\n".join(L) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--casos", required=True)
    p.add_argument("--v0", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes"))
    a = p.parse_args()
    with open(a.casos, encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    with open(a.v0, encoding="utf-8") as f:
        v0 = json.load(f)
    with open(a.baseline, encoding="utf-8") as f:
        base = json.load(f)
    texto = comparar(casos, v0, base)
    ruta = os.path.join(a.salida, f"comparacion_baseline_{datetime.now():%Y%m%d_%H%M}.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Reporte: {ruta}")


if __name__ == "__main__":
    main()
