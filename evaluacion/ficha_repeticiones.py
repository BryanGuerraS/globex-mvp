"""Ficha de la clase (As-Is / Propuesta / Diferencia / Al repetir) a partir de varias corridas.

Junta N corridas de evaluar.py de Globix (y, si las hay, la calificación del juez de cada
una) con la corrida del baseline de reglas, y calcula por métrica: promedio, mínimo y
máximo entre corridas, la diferencia contra el baseline y la huella SHA-256 del banco
usado (para demostrar que no cambió entre corridas).

Uso:
    python evaluacion/ficha_repeticiones.py --casos evaluacion/reservado/casos_reservados.json \\
        --banco evaluacion/reservado/Globex_Banco_Pruebas_v3_Pendientes_Depurados.txt \\
        --v0 r1.json r2.json r3.json --juez-v0 dir1 dir2 dir3 \\
        --baseline evaluacion/reportes/baseline_reglas/resultados_X.json --juez-baseline dir_b \\
        --exito-csv evaluacion/reportes/corrida_oficial_20261109_exito_por_caso.csv

`--exito-csv` agrega una corrida de la que solo se conserva el éxito por caso (la
corrida oficial del 09/11). Las carpetas del juez son las que genera juez_llm.py
(clave.csv + hoja_juez.csv).
"""

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
from datetime import datetime
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion import revision_humana as rh  # noqa: E402
from metricas import clopper_pearson  # noqa: E402


def sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def exito_de_resultados(ruta: str) -> Dict[str, bool]:
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)["resultados"]
    return {cid: bool(rs[0]["exito"]) for cid, rs in datos.items() if rs}


def exito_de_csv(ruta: str) -> Dict[str, bool]:
    """CSV 'id;✅' o 'id;❌' (log de la corrida oficial)."""
    salida = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if ";" in linea:
                cid, marca = linea.strip().split(";", 1)
                salida[cid] = "✅" in marca
    return salida


def juez_de_carpeta(carpeta: str) -> Dict[str, Optional[bool]]:
    """caso -> True/False según la atención correcta del juez; None si no hubo veredicto."""
    clave = {f["id"]: f["caso"] for f in rh.leer_csv(os.path.join(carpeta, "clave.csv"))}
    hoja = rh.leer_hoja(os.path.join(carpeta, "hoja_juez.csv"))
    salida = {}
    for rid, v in hoja.items():
        a = rh.atencion_correcta(v)
        salida[clave[rid]] = None if a is None else a == "S"
    return salida


def tasa(valores: Dict[str, Optional[bool]], ids: List[str]) -> Dict:
    validos = [valores[i] for i in ids if valores.get(i) is not None]
    k, n = sum(validos), len(validos)
    li, ls = clopper_pearson(k, n) if n else (None, None)
    return {"exitos": k, "n": n, "valor": k / n if n else None, "ic95": [li, ls]}


def resumen_corridas(corridas: List[Dict[str, Optional[bool]]], ids: List[str]) -> Dict:
    tasas = [tasa(c, ids) for c in corridas]
    valores = [t["valor"] for t in tasas if t["valor"] is not None]
    return {
        "corridas": tasas,
        "promedio": statistics.mean(valores) if valores else None,
        "minimo": min(valores) if valores else None,
        "maximo": max(valores) if valores else None,
        "desviacion": statistics.stdev(valores) if len(valores) > 1 else 0.0,
    }


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.1f} %"


def _pp(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:+.1f} pp"


def ficha(casos: List[Dict], banco: Optional[str], v0_exito: List[Dict], v0_juez: List[Dict],
          base_exito: Dict, base_juez: Optional[Dict]) -> str:
    ids = sorted(c["id"] for c in casos)
    # Métrica del juez: solo casos con veredicto en el baseline, para comparar lo mismo
    ids_juez = [i for i in ids if base_juez is None or base_juez.get(i) is not None]
    L = [f"# Ficha de modelamiento · Globix v0 contra baseline · {datetime.now():%d/%m/%Y %H:%M}", ""]
    if banco:
        L += [f"Banco: `{os.path.basename(banco)}` · SHA-256 `{sha256(banco)}` · {len(ids)} casos.", ""]
    L += ["| Métrica | As-Is (reglas sin LLM) | Propuesta (Globix v0, promedio) | Diferencia | Al repetir (mín.–máx.) | Corridas |",
          "| --- | --- | --- | --- | --- | --: |"]
    filas = [("Éxito de tarea (checks)", v0_exito, base_exito, ids)]
    if v0_juez and base_juez is not None:
        filas.append(("Atención correcta (juez)", v0_juez, base_juez, ids_juez))
    detalle = []
    for nombre, corridas, base, ids_m in filas:
        r = resumen_corridas(corridas, ids_m)
        b = tasa(base, ids_m)
        dif = None if r["promedio"] is None or b["valor"] is None else r["promedio"] - b["valor"]
        L.append(f"| {nombre} | {_pct(b['valor'])} ({b['exitos']}/{b['n']}) | {_pct(r['promedio'])} | {_pp(dif)} | "
                 f"{_pct(r['minimo'])} – {_pct(r['maximo'])} | {len(corridas)} |")
        detalle.append((nombre, r, b))
    L += ["", "El baseline de reglas es determinista: repetirlo da siempre el mismo resultado.", ""]
    for nombre, r, b in detalle:
        L += [f"## {nombre}: detalle por corrida", "", "| Corrida | Aciertos | % | IC 95 % (Clopper-Pearson) | Diferencia contra reglas |",
              "| --: | --: | --: | --- | --: |"]
        for i, t in enumerate(r["corridas"], 1):
            L.append(f"| {i} | {t['exitos']}/{t['n']} | {_pct(t['valor'])} | [{_pct(t['ic95'][0])}, {_pct(t['ic95'][1])}] | "
                     f"{_pp(t['valor'] - b['valor'] if t['valor'] is not None else None)} |")
        L += ["", f"Desviación estándar entre corridas: {r['desviacion'] * 100:.2f} pp.", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--casos", required=True)
    p.add_argument("--banco")
    p.add_argument("--v0", nargs="*", default=[], help="resultados_*.json de evaluar.py (Globix)")
    p.add_argument("--exito-csv", nargs="*", default=[], help="corridas de las que solo hay éxito por caso")
    p.add_argument("--juez-v0", nargs="*", default=[], help="carpetas del juez, una por corrida de Globix")
    p.add_argument("--baseline", required=True)
    p.add_argument("--juez-baseline")
    p.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes"))
    a = p.parse_args(argv)
    with open(a.casos, encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    v0_exito = [exito_de_csv(r) for r in a.exito_csv] + [exito_de_resultados(r) for r in a.v0]
    v0_juez = [juez_de_carpeta(d) for d in a.juez_v0]
    base_juez = juez_de_carpeta(a.juez_baseline) if a.juez_baseline else None
    texto = ficha(casos, a.banco, v0_exito, v0_juez, exito_de_resultados(a.baseline), base_juez)
    os.makedirs(a.salida, exist_ok=True)
    ruta = os.path.join(a.salida, f"ficha_repeticiones_{datetime.now():%Y%m%d_%H%M%S}.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Ficha: {ruta}")


if __name__ == "__main__":
    main()
