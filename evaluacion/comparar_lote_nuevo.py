"""Compara Globix v0, Globix v1 y el baseline de reglas según el pre-registro del lote nuevo.

Aplica las reglas de docs/prerregistro_lote_nuevo.md:
  1. Checks automáticos sobre todos los casos (incluidos los de validación parcial).
  2. Juez (atención correcta) solo sobre los casos "Listo" con veredicto en todas las corridas
     de todas las opciones.
  3. Exactitud de precio y peso (K2) sobre los casos que esperan una cotización.
  4. Por opción: promedio, mínimo y máximo entre corridas, e IC 95 % de Clopper-Pearson por corrida.
  5. Diferencias v1 − v0 y cada versión − reglas, con IC 95 % por bootstrap de casos
     (5 000 remuestreos, semilla 17; cada caso es su propio grupo). Con varias corridas, cada
     caso aporta su tasa media de acierto entre corridas.
  6. Contrapeso: cotizaciones indebidas y derivaciones innecesarias por opción.

Uso:
    python evaluacion/comparar_lote_nuevo.py --casos <casos_reservados.json> --banco <lote>.txt \\
        --v0 r1.json r2.json r3.json --juez-v0 d1 d2 d3 \\
        --v1 s1.json s2.json s3.json --juez-v1 e1 e2 e3 \\
        --reglas b.json --juez-reglas db --commit-v1 <hash>
"""

import argparse
import json
import os
import random
import statistics
import sys
from datetime import datetime
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion.ficha_repeticiones import (  # noqa: E402
    _pct, _pp, exito_de_resultados, juez_de_carpeta, resumen_corridas, sha256,
)

REMUESTREOS = 5000
SEMILLA = 17
OPCIONES = ("v0", "v1", "reglas")
NOMBRES = {"v0": "Globix v0", "v1": "Globix v1", "reglas": "Reglas sin LLM"}


def checks_de_resultados(ruta: str) -> Dict[str, Dict[str, bool]]:
    """caso -> {nombre del check: ok} de la primera repetición de una corrida."""
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)["resultados"]
    return {cid: {c["check"]: bool(c["ok"]) for c in rs[0]["checks"]} for cid, rs in datos.items() if rs}


def check_como_acierto(checks: Dict[str, Dict[str, bool]], nombre: str) -> Dict[str, Optional[bool]]:
    """caso -> resultado del check (None si el caso no tiene ese check)."""
    return {cid: cs.get(nombre) for cid, cs in checks.items()}


def bootstrap_diferencia(a: List[Dict[str, Optional[bool]]], b: List[Dict[str, Optional[bool]]],
                         ids: List[str], remuestreos: int = REMUESTREOS, semilla: int = SEMILLA) -> Dict:
    """Diferencia de tasas a − b con IC 95 % por bootstrap de casos (tasa media entre corridas)."""
    def media_por_caso(corridas):
        salida = {}
        for i in ids:
            vals = [c[i] for c in corridas if c.get(i) is not None]
            if vals:
                salida[i] = sum(vals) / len(vals)
        return salida

    ma, mb = media_por_caso(a), media_por_caso(b)
    comunes = [i for i in ids if i in ma and i in mb]
    if not comunes:
        return {"diferencia": None, "ic95": [None, None], "n": 0}
    difs = [ma[i] - mb[i] for i in comunes]
    rng = random.Random(semilla)
    n = len(difs)
    medias = sorted(sum(difs[rng.randrange(n)] for _ in range(n)) / n for _ in range(remuestreos))
    return {"diferencia": sum(difs) / n, "ic95": [medias[int(0.025 * remuestreos)], medias[int(0.975 * remuestreos) - 1]],
            "n": n}


def contar_fallas(checks_runs: List[Dict[str, Dict[str, bool]]], nombre: str) -> Dict:
    """Fallas de un check de contrapeso por corrida (promedio, mínimo, máximo)."""
    por_corrida = [sum(1 for cs in run.values() if cs.get(nombre) is False) for run in checks_runs]
    n = max((sum(1 for cs in run.values() if nombre in cs) for run in checks_runs), default=0)
    return {"por_corrida": por_corrida, "n": n,
            "promedio": statistics.mean(por_corrida) if por_corrida else None,
            "minimo": min(por_corrida) if por_corrida else None, "maximo": max(por_corrida) if por_corrida else None}


def comparar(casos: List[Dict], runs: Dict[str, List[str]], jueces: Dict[str, List[str]]) -> Dict:
    ids = sorted(c["id"] for c in casos)
    listos = {c["id"] for c in casos if c.get("banco", {}).get("estado_referencia", "Listo") == "Listo"}
    ids_cotiza = sorted(c["id"] for c in casos if c.get("esperado", {}).get("cotizacion"))

    checks = {o: [checks_de_resultados(r) for r in runs[o]] for o in OPCIONES}
    exito = {o: [exito_de_resultados(r) for r in runs[o]] for o in OPCIONES}
    k2 = {o: [check_como_acierto(c, "argumentos_cotizacion") for c in checks[o]] for o in OPCIONES}
    juez = {o: [juez_de_carpeta(d) for d in jueces.get(o, [])] for o in OPCIONES}
    hay_juez = all(juez[o] for o in OPCIONES)
    ids_juez = [i for i in ids if i in listos and hay_juez
                and all(j.get(i) is not None for o in OPCIONES for j in juez[o])]

    metricas = [("checks", "Éxito de tarea (checks)", exito, ids),
                ("k2", "K2 · precio y peso correctos", k2, ids_cotiza)]
    if hay_juez:
        metricas.append(("juez", "Atención correcta (juez, casos Listo)", juez, ids_juez))

    salida = {"metricas": {}, "contrapeso": {}}
    for clave, nombre, datos, ids_m in metricas:
        salida["metricas"][clave] = {
            "nombre": nombre, "n_casos": len(ids_m),
            "opciones": {o: resumen_corridas(datos[o], ids_m) for o in OPCIONES},
            "diferencias": {
                "v1 − v0": bootstrap_diferencia(datos["v1"], datos["v0"], ids_m),
                "v1 − reglas": bootstrap_diferencia(datos["v1"], datos["reglas"], ids_m),
                "v0 − reglas": bootstrap_diferencia(datos["v0"], datos["reglas"], ids_m),
            },
        }
    for clave, nombre in (("no_cotiza_indebidamente", "Cotizaciones indebidas"),
                          ("no_deriva", "Derivaciones innecesarias")):
        salida["contrapeso"][clave] = {"nombre": nombre, "opciones": {o: contar_fallas(checks[o], clave) for o in OPCIONES}}
    return salida


def a_markdown(r: Dict, banco: Optional[str], commit_v1: str, n_casos: int) -> str:
    L = [f"# Lote nuevo · Globix v0, v1 y reglas · {datetime.now():%d/%m/%Y %H:%M}", ""]
    if banco:
        L.append(f"Banco: `{os.path.basename(banco)}` · SHA-256 `{sha256(banco)}` · {n_casos} casos.")
    L += [f"Globix v0: commit `92859b0` · Globix v1: commit `{commit_v1 or '—'}` · reglas: herramientas del commit de la v1.",
          "Reglas de medición: `docs/prerregistro_lote_nuevo.md`. El juez no está validado contra un revisor humano.", ""]
    for m in r["metricas"].values():
        L += [f"## {m['nombre']} ({m['n_casos']} casos)", "",
              "| Opción | Promedio | Mín.–máx. | Corridas (aciertos/n, IC 95 %) |", "| --- | --: | --- | --- |"]
        for o in OPCIONES:
            s = m["opciones"][o]
            det = "; ".join(f"{t['exitos']}/{t['n']} [{_pct(t['ic95'][0])}, {_pct(t['ic95'][1])}]" for t in s["corridas"])
            L.append(f"| {NOMBRES[o]} | {_pct(s['promedio'])} | {_pct(s['minimo'])} – {_pct(s['maximo'])} | {det} |")
        L += ["", "| Diferencia | Valor | IC 95 % (bootstrap de casos) |", "| --- | --: | --- |"]
        for nombre, d in m["diferencias"].items():
            L.append(f"| {nombre} | {_pp(d['diferencia'])} | [{_pp(d['ic95'][0])}, {_pp(d['ic95'][1])}] |")
        L.append("")
    L += ["## Contrapeso", "", "| Falla | " + " | ".join(NOMBRES[o] for o in OPCIONES) + " |",
          "| --- | " + " | ".join("---" for _ in OPCIONES) + " |"]
    for c in r["contrapeso"].values():
        celdas = []
        for o in OPCIONES:
            s = c["opciones"][o]
            celdas.append(f"{s['promedio']:.1f} de {s['n']} ({s['minimo']}–{s['maximo']})" if s["promedio"] is not None else "—")
        L.append(f"| {c['nombre']} | " + " | ".join(celdas) + " |")
    L += ["", f"Bootstrap: {REMUESTREOS} remuestreos, semilla {SEMILLA}. Con varias corridas, cada caso aporta su tasa media."]
    return "\n".join(L) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--casos", required=True)
    p.add_argument("--banco")
    for o in OPCIONES:
        p.add_argument(f"--{o}", nargs="+", required=True, help=f"resultados_*.json de {NOMBRES[o]}")
        p.add_argument(f"--juez-{o}", nargs="*", default=[], help=f"carpetas del juez de {NOMBRES[o]}")
    p.add_argument("--commit-v1", default="")
    p.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes"))
    a = p.parse_args(argv)
    with open(a.casos, encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    runs = {o: getattr(a, o) for o in OPCIONES}
    jueces = {o: getattr(a, f"juez_{o}") for o in OPCIONES}
    r = comparar(casos, runs, jueces)
    texto = a_markdown(r, a.banco, a.commit_v1, len(casos))
    os.makedirs(a.salida, exist_ok=True)
    marca = f"{datetime.now():%Y%m%d_%H%M%S}"
    with open(os.path.join(a.salida, f"comparacion_lote_nuevo_{marca}.md"), "w", encoding="utf-8") as f:
        f.write(texto)
    with open(os.path.join(a.salida, f"comparacion_lote_nuevo_{marca}.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(texto)


if __name__ == "__main__":
    main()
