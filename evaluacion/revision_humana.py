"""Revisión humana doble de Globix con la rúbrica de docs/rubrica_calidad.md.

Dos pasos:

    # 1. Elegir la muestra y generar las hojas de los dos revisores
    python evaluacion/revision_humana.py exportar --resultados evaluacion/reportes/resultados_X.json --muestra 60

    # 2. Medir el acuerdo (kappa de Cohen) y, tras el consenso, el resultado final
    python evaluacion/revision_humana.py kappa --a hoja_revisor_A.csv --b hoja_revisor_B.csv --clave clave.csv
    python evaluacion/revision_humana.py kappa ... --consenso discrepancias.csv

Las hojas son CSV con punto y coma (se abren directo en Excel en español) y
también se aceptan con coma (exportadas desde Google Sheets). No llama al LLM.
"""

import argparse
import csv
import json
import os
import random
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from metricas import clopper_pearson  # noqa: E402

CRITERIOS = {
    "C1_necesidad": "Atiende la necesidad",
    "C2_informacion": "Información correcta",
    "C3_datos": "Datos pertinentes",
    "C4_procedimiento": "Procedimiento y alcance",
    "C5_derivacion": "Derivación",
    "C6_claridad": "Claridad y tono",
}
PRINCIPALES = ("C1_necesidad", "C2_informacion", "C3_datos", "C4_procedimiento", "C5_derivacion")
SOLO_CON_NA = ("C5_derivacion",)
ATENCION = "atencion_correcta"
KAPPA_MINIMO = 0.6
COLUMNAS_HOJA = ["id", "conversacion", *CRITERIOS, "comentario"]


# ------------------------------------------------------------------ etiquetas

def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(valor) -> Optional[str]:
    """'Sí', 's', '1' -> 'S'; 'no', '0' -> 'N'; 'N/A', 'no aplica' -> 'NA'; vacío -> None."""
    texto = _sin_tildes(str(valor or "")).strip().upper().replace(" ", "").replace("/", "")
    if not texto:
        return None
    if texto in ("S", "SI", "1", "TRUE", "VERDADERO"):
        return "S"
    if texto in ("N", "NO", "0", "FALSE", "FALSO"):
        return "N"
    if texto in ("NA", "NOAPLICA"):
        return "NA"
    raise ValueError(f"Valor no válido: {valor!r} (usa S, N o NA)")


def atencion_correcta(fila: Dict[str, Optional[str]]) -> Optional[str]:
    """Resultado principal de la rúbrica: C1–C4 en S y C5 en S o NA."""
    valores = [fila.get(c) for c in PRINCIPALES]
    if any(v is None for v in valores):
        return None
    ok = all(fila[c] == "S" for c in PRINCIPALES if c not in SOLO_CON_NA) and all(
        fila[c] in ("S", "NA") for c in SOLO_CON_NA
    )
    return "S" if ok else "N"


# ------------------------------------------------------------------ acuerdo

def kappa_cohen(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """Kappa de Cohen para dos revisores. None si no está definido (los dos usan una sola categoría)."""
    if len(a) != len(b) or not a:
        raise ValueError("Las dos listas deben tener el mismo largo y no estar vacías")
    n = len(a)
    acuerdo = sum(x == y for x, y in zip(a, b)) / n
    categorias = set(a) | set(b)
    esperado = sum((a.count(c) / n) * (b.count(c) / n) for c in categorias)
    if esperado >= 1:
        return None
    return (acuerdo - esperado) / (1 - esperado)


def porcentaje_acuerdo(a: Sequence[str], b: Sequence[str]) -> float:
    return sum(x == y for x, y in zip(a, b)) / len(a)


def ic_bootstrap_kappa(a: Sequence[str], b: Sequence[str], repeticiones: int = 2000,
                       semilla: int = 13) -> Optional[Tuple[float, float]]:
    """IC 95 % de kappa remuestreando conversaciones (percentiles 2.5 y 97.5)."""
    azar = random.Random(semilla)
    n = len(a)
    valores = []
    for _ in range(repeticiones):
        idx = [azar.randrange(n) for _ in range(n)]
        k = kappa_cohen([a[i] for i in idx], [b[i] for i in idx])
        if k is not None:
            valores.append(k)
    if len(valores) < repeticiones * 0.5:
        return None
    valores.sort()
    return valores[int(0.025 * (len(valores) - 1))], valores[int(0.975 * (len(valores) - 1))]


def interpretar_kappa(k: Optional[float]) -> str:
    if k is None:
        return "no definido"
    if k < 0.40:
        return "débil"
    if k <= 0.60:
        return "moderado"
    if k <= 0.80:
        return "sustancial"
    return "casi perfecto"


# ------------------------------------------------------------------ exportar

def texto_conversacion(turnos: List[Dict]) -> str:
    lineas = []
    for t in turnos:
        lineas.append(f"CLIENTE: {t.get('cliente', '')}")
        for r in t.get("respuestas") or []:
            lineas.append(f"GLOBIX: {r}")
    return "\n".join(lineas)


def categoria_de(caso_id: str) -> str:
    return caso_id.split("-")[0]


def elegir_muestra(caso_ids: Sequence[str], n: int, semilla: int = 7) -> List[str]:
    """Muestra estratificada por tipo de caso (prefijo del id), proporcional y con al menos 1 por tipo."""
    azar = random.Random(semilla)
    estratos = defaultdict(list)
    for c in sorted(caso_ids):
        estratos[categoria_de(c)].append(c)
    if n >= len(caso_ids):
        return sorted(caso_ids)
    total = len(caso_ids)
    cupos = {k: max(1, round(n * len(v) / total)) for k, v in estratos.items()}
    # Ajustar al tamaño pedido: quitar o sumar en los estratos más grandes
    while sum(cupos.values()) > n:
        k = max((k for k in cupos if cupos[k] > 1), key=lambda k: cupos[k], default=None)
        if k is None:
            break
        cupos[k] -= 1
    while sum(cupos.values()) < n:
        k = max((k for k in cupos if cupos[k] < len(estratos[k])), key=lambda k: len(estratos[k]) - cupos[k])
        cupos[k] += 1
    muestra = []
    for k, casos in estratos.items():
        muestra.extend(azar.sample(casos, min(cupos[k], len(casos))))
    return sorted(muestra)


def exportar(resultados_json: str, muestra: int, salida: str, semilla: int = 7) -> Dict[str, str]:
    with open(resultados_json, encoding="utf-8") as f:
        datos = json.load(f)
    resultados = datos["resultados"]
    elegidos = elegir_muestra(list(resultados), muestra, semilla)
    orden = elegidos[:]
    random.Random(semilla + 1).shuffle(orden)  # las hojas no siguen el orden por tipo de caso

    os.makedirs(salida, exist_ok=True)
    filas, clave = [], []
    for i, caso in enumerate(orden, 1):
        corrida = resultados[caso][0]  # primera repetición
        rid = f"R{i:03d}"
        filas.append({"id": rid, "conversacion": texto_conversacion(corrida["turnos"]),
                      **{c: "" for c in CRITERIOS}, "comentario": ""})
        clave.append({"id": rid, "caso": caso, "categoria": categoria_de(caso), "chat_id": corrida.get("chat_id", ""),
                      "archivo": os.path.basename(resultados_json)})

    rutas = {}
    for revisor in ("A", "B"):
        rutas[revisor] = os.path.join(salida, f"hoja_revisor_{revisor}.csv")
        escribir_csv(rutas[revisor], COLUMNAS_HOJA, filas)
    rutas["clave"] = os.path.join(salida, "clave.csv")
    escribir_csv(rutas["clave"], ["id", "caso", "categoria", "chat_id", "archivo"], clave)
    return rutas


# ------------------------------------------------------------------ CSV

def escribir_csv(ruta: str, columnas: Sequence[str], filas: List[Dict]):
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columnas), delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def leer_csv(ruta: str) -> List[Dict[str, str]]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        cabecera = f.readline()
        f.seek(0)
        delimitador = ";" if cabecera.count(";") >= cabecera.count(",") else ","
        return [{(k or "").strip(): (v or "") for k, v in fila.items()} for fila in csv.DictReader(f, delimiter=delimitador)]


def leer_hoja(ruta: str) -> Dict[str, Dict[str, Optional[str]]]:
    """id -> {criterio: S/N/NA, 'comentario', 'conversacion'}. Falla si hay valores inválidos."""
    hoja = {}
    for n, fila in enumerate(leer_csv(ruta), 2):
        rid = fila.get("id", "").strip()
        if not rid:
            continue
        etiquetas = {}
        for c in CRITERIOS:
            try:
                etiquetas[c] = normalizar(fila.get(c))
            except ValueError as e:
                raise ValueError(f"{os.path.basename(ruta)}, fila {n}, {c}: {e}") from None
            if etiquetas[c] == "NA" and c not in SOLO_CON_NA:
                raise ValueError(f"{os.path.basename(ruta)}, fila {n}, {c}: NA solo se permite en C5")
        etiquetas["comentario"] = fila.get("comentario", "")
        etiquetas["conversacion"] = fila.get("conversacion", "")
        hoja[rid] = etiquetas
    return hoja


# ------------------------------------------------------------------ kappa y consenso

def _etiquetas(hoja: Dict, ids: List[str], criterio: str) -> List[Optional[str]]:
    if criterio == ATENCION:
        return [atencion_correcta(hoja[i]) for i in ids]
    return [hoja[i][criterio] for i in ids]


def medir_acuerdo(a: Dict, b: Dict) -> Dict:
    ids = sorted(set(a) & set(b))
    faltan = sorted(set(a) ^ set(b))
    resultado = {"n": len(ids), "ids_sin_par": faltan, "criterios": {}, "incompletas": []}
    for criterio in [ATENCION, *CRITERIOS]:
        va, vb = _etiquetas(a, ids, criterio), _etiquetas(b, ids, criterio)
        pares = [(x, y) for x, y in zip(va, vb) if x is not None and y is not None]
        if not pares:
            resultado["criterios"][criterio] = {"n": 0}
            continue
        xa, xb = [p[0] for p in pares], [p[1] for p in pares]
        k = kappa_cohen(xa, xb)
        resultado["criterios"][criterio] = {
            "n": len(pares),
            "acuerdo": porcentaje_acuerdo(xa, xb),
            "kappa": k,
            "ic95": ic_bootstrap_kappa(xa, xb),
            "interpretacion": interpretar_kappa(k),
        }
    resultado["incompletas"] = [i for i in ids if any(a[i][c] is None or b[i][c] is None for c in CRITERIOS)]
    return resultado


def discrepancias(a: Dict, b: Dict) -> List[Dict]:
    filas = []
    for rid in sorted(set(a) & set(b)):
        for c in CRITERIOS:
            if a[rid][c] != b[rid][c]:
                filas.append({"id": rid, "criterio": c, "valor_A": a[rid][c] or "", "valor_B": b[rid][c] or "",
                              "consenso": "", "comentario_A": a[rid]["comentario"],
                              "comentario_B": b[rid]["comentario"], "conversacion": a[rid]["conversacion"]})
    return filas


def aplicar_consenso(a: Dict, b: Dict, filas_consenso: List[Dict]) -> Dict[str, Dict[str, Optional[str]]]:
    """Etiquetas finales: donde A y B coinciden, ese valor; donde no, el del consenso (obligatorio)."""
    acordado = {}
    for fila in filas_consenso:
        valor = normalizar(fila.get("consenso"))
        if valor is None:
            raise ValueError(f"Falta el consenso de {fila.get('id')} / {fila.get('criterio')}")
        acordado[(fila["id"].strip(), fila["criterio"].strip())] = valor
    final = {}
    for rid in sorted(set(a) & set(b)):
        final[rid] = {}
        for c in CRITERIOS:
            if a[rid][c] == b[rid][c]:
                final[rid][c] = a[rid][c]
            elif (rid, c) in acordado:
                final[rid][c] = acordado[(rid, c)]
            else:
                raise ValueError(f"{rid} / {c}: A y B no coinciden y no está en el archivo de consenso")
    return final


def resultado_final(final: Dict, clave: Optional[Dict[str, Dict]] = None) -> Dict:
    """% de atención correcta (y por criterio) con IC 95 % de Clopper-Pearson, en total y por tipo de caso."""
    def resumen(ids):
        out = {}
        for c in [ATENCION, *CRITERIOS]:
            vals = [atencion_correcta(final[i]) if c == ATENCION else final[i][c] for i in ids]
            vals = [v for v in vals if v in ("S", "N")]
            si = vals.count("S")
            out[c] = {"exitos": si, "n": len(vals), "valor": si / len(vals) if vals else None,
                      "ic95": list(clopper_pearson(si, len(vals))) if vals else None}
        return out

    ids = sorted(final)
    res = {"total": resumen(ids), "por_categoria": {}}
    if clave:
        grupos = defaultdict(list)
        for i in ids:
            grupos[clave.get(i, {}).get("categoria", "?")].append(i)
        res["por_categoria"] = {k: resumen(v)[ATENCION] for k, v in sorted(grupos.items())}
    return res


# ------------------------------------------------------------------ reporte

def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def _ic(ic) -> str:
    return "—" if not ic else f"[{ic[0]:.2f}, {ic[1]:.2f}]"


NOMBRES = {ATENCION: "**Atención correcta**", **CRITERIOS}


def tabla_acuerdo(acuerdo: Dict) -> List[str]:
    """Tabla de acuerdo (κ por criterio) y la lectura según KAPPA_MINIMO."""
    lineas = ["| Criterio | n | % acuerdo | κ de Cohen | IC 95 % (bootstrap) | Lectura |",
              "| --- | --: | --: | --: | --- | --- |"]
    for c, m in acuerdo["criterios"].items():
        if not m.get("n"):
            continue
        k = "—" if m["kappa"] is None else f"{m['kappa']:.2f}"
        lineas.append(f"| {NOMBRES[c]} | {m['n']} | {_pct(m['acuerdo'])} | {k} | {_ic(m['ic95'])} | {m['interpretacion']} |")
    k_principal = acuerdo["criterios"].get(ATENCION, {}).get("kappa")
    lineas.append("")
    if k_principal is None:
        lineas.append("κ de la atención correcta no definido (se usó una sola categoría): reportar el % de acuerdo.")
    elif k_principal < KAPPA_MINIMO:
        lineas.append(f"**κ < {KAPPA_MINIMO}:** acuerdo insuficiente; revisar los criterios con menos acuerdo.")
    else:
        lineas.append(f"κ ≥ {KAPPA_MINIMO}: acuerdo suficiente.")
    return lineas


def tabla_resultado(final: Dict) -> List[str]:
    """% que cumple cada criterio (IC de Clopper-Pearson) y atención correcta por tipo de caso."""
    lineas = ["| Criterio | Cumple | n | % | IC 95 % (Clopper-Pearson) |", "| --- | --: | --: | --: | --- |"]
    for c, m in final["total"].items():
        if m["n"]:
            lineas.append(f"| {NOMBRES[c]} | {m['exitos']} | {m['n']} | {_pct(m['valor'])} | "
                          f"[{_pct(m['ic95'][0])}, {_pct(m['ic95'][1])}] |")
    if final["por_categoria"]:
        lineas += ["", "### Atención correcta por tipo de caso", "",
                   "| Tipo | Correctas | n | % | IC 95 % |", "| --- | --: | --: | --: | --- |"]
        for cat, m in final["por_categoria"].items():
            if m["n"]:
                lineas.append(f"| {cat} | {m['exitos']} | {m['n']} | {_pct(m['valor'])} | "
                              f"[{_pct(m['ic95'][0])}, {_pct(m['ic95'][1])}] |")
    return lineas


def reporte_markdown(acuerdo: Dict, final: Optional[Dict] = None) -> str:
    lineas = [f"# Revisión humana doble · {datetime.now():%d/%m/%Y %H:%M}", "",
              f"Conversaciones revisadas por ambos: **{acuerdo['n']}**.", ""]
    if acuerdo["ids_sin_par"]:
        lineas += [f"Aviso: filas que están en una sola hoja: {', '.join(acuerdo['ids_sin_par'])}.", ""]
    if acuerdo["incompletas"]:
        lineas += [f"Aviso: filas con celdas vacías (no cuentan en ese criterio): {', '.join(acuerdo['incompletas'])}.", ""]
    lineas += ["## Acuerdo entre revisores", "", *tabla_acuerdo(acuerdo)]
    if final:
        lineas += ["", "## Resultado tras el consenso", "", *tabla_resultado(final)]
    return "\n".join(lineas) + "\n"


# ------------------------------------------------------------------ CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    ex = sub.add_parser("exportar", help="Elegir la muestra y generar las hojas de los revisores")
    ex.add_argument("--resultados", required=True, help="JSON generado por evaluar.py")
    ex.add_argument("--muestra", type=int, default=60)
    ex.add_argument("--semilla", type=int, default=7)
    ex.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes", "revision_humana"))
    ka = sub.add_parser("kappa", help="Medir el acuerdo y, con --consenso, el resultado final")
    ka.add_argument("--a", required=True)
    ka.add_argument("--b", required=True)
    ka.add_argument("--clave")
    ka.add_argument("--consenso")
    ka.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes", "revision_humana"))
    args = parser.parse_args(argv)

    if args.comando == "exportar":
        rutas = exportar(args.resultados, args.muestra, args.salida, args.semilla)
        print(f"Hojas listas: {rutas['A']} y {rutas['B']}\nClave (no se entrega a los revisores): {rutas['clave']}")
        return

    a, b = leer_hoja(args.a), leer_hoja(args.b)
    acuerdo = medir_acuerdo(a, b)
    os.makedirs(args.salida, exist_ok=True)
    final = None
    if args.consenso:
        clave = {f["id"]: f for f in leer_csv(args.clave)} if args.clave else None
        final = resultado_final(aplicar_consenso(a, b, leer_csv(args.consenso)), clave)
    else:
        ruta_disc = os.path.join(args.salida, "discrepancias.csv")
        escribir_csv(ruta_disc, ["id", "criterio", "valor_A", "valor_B", "consenso", "comentario_A",
                                 "comentario_B", "conversacion"], discrepancias(a, b))
        print(f"Discrepancias para el consenso: {ruta_disc}")
    texto = reporte_markdown(acuerdo, final)
    ruta_md = os.path.join(args.salida, f"reporte_revision_{datetime.now():%Y%m%d_%H%M}.md")
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Reporte: {ruta_md}")


if __name__ == "__main__":
    main()
