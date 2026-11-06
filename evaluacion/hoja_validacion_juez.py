"""Hoja para validar el LLM juez contra UN revisor humano.

Mezcla conversaciones reales ya juzgadas (incluye todas en las que el juez y
los checks automáticos no coinciden) con conversaciones con errores sembrados,
las desordena y les pone ids nuevos (V001…). El revisor no sabe cuáles tienen
errores sembrados ni qué dijo el juez.

Genera, en <carpeta>/validacion_juez/:
- hoja_humano.csv   -> la llena el revisor (S / N / NA) siguiendo docs/rubrica_calidad.md
- hoja_juez.csv     -> veredictos del juez con los mismos ids (no se entrega al revisor)
- clave.csv         -> origen de cada fila (no se entrega al revisor)

Luego:
    python evaluacion/revision_humana.py kappa --a <carpeta>/validacion_juez/hoja_humano.csv \\
        --b <carpeta>/validacion_juez/hoja_juez.csv --salida <carpeta>/validacion_juez
"""

import argparse
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion import revision_humana as rh  # noqa: E402

CARPETA = os.path.join(REPO, "evaluacion", "reportes", "revision_humana")


def armar(carpeta: str = CARPETA, reales: int = 30, sembradas: int = 10, semilla: int = 23) -> str:
    azar = random.Random(semilla)
    hoja = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "hoja_revisor_A.csv"))}
    juez = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "hoja_juez.csv"))}
    clave_dev = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "clave.csv"))}
    hoja_s = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "hoja_sembrada.csv"))}
    juez_s = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "hoja_juez_sembrada.csv"))}
    clave_s = {f["id"]: f for f in rh.leer_csv(os.path.join(carpeta, "clave_sembrada.csv"))}

    # Siempre entran las conversaciones donde el juez dijo N (incluye los desacuerdos con los checks)
    juez_n = sorted(i for i in juez if rh.atencion_correcta(rh.leer_hoja(os.path.join(carpeta, "hoja_juez.csv"))[i]) == "N")
    resto = sorted(set(juez) - set(juez_n))
    elegidas = juez_n + azar.sample(resto, max(0, reales - len(juez_n)))
    por_tipo = {}
    for sid, c in sorted(clave_s.items()):
        por_tipo.setdefault(c["tipo"], []).append(sid)
    sem = []
    while len(sem) < sembradas and any(por_tipo.values()):  # repartidas entre los tipos de error
        for tipo in sorted(por_tipo):
            if por_tipo[tipo] and len(sem) < sembradas:
                sem.append(por_tipo[tipo].pop(azar.randrange(len(por_tipo[tipo]))))

    filas = [("real", i) for i in elegidas] + [("sembrada", i) for i in sem]
    azar.shuffle(filas)
    salida = os.path.join(carpeta, "validacion_juez")
    os.makedirs(salida, exist_ok=True)
    humano, jueces, clave = [], [], []
    for n, (fuente, origen) in enumerate(filas, 1):
        vid = f"V{n:03d}"
        conv = (hoja if fuente == "real" else hoja_s)[origen]["conversacion"]
        veredicto = (juez if fuente == "real" else juez_s)[origen]
        humano.append({"id": vid, "conversacion": conv})
        jueces.append({**{c: veredicto[c] for c in rh.CRITERIOS}, "id": vid, "conversacion": conv,
                       "comentario": veredicto.get("comentario", "")})
        extra = clave_dev[origen] if fuente == "real" else clave_s[origen]
        clave.append({"id": vid, "fuente": fuente, "origen": origen,
                      "caso": extra.get("caso", ""), "tipo_error": extra.get("tipo", ""),
                      "categoria": extra.get("categoria") or "SEMBRADA"})
    rh.escribir_csv(os.path.join(salida, "hoja_humano.csv"), rh.COLUMNAS_HOJA, humano)
    rh.escribir_csv(os.path.join(salida, "hoja_juez.csv"), rh.COLUMNAS_HOJA, jueces)
    rh.escribir_csv(os.path.join(salida, "clave.csv"),
                    ["id", "fuente", "origen", "caso", "tipo_error", "categoria"], clave)
    return salida


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--carpeta", default=CARPETA)
    p.add_argument("--reales", type=int, default=30)
    p.add_argument("--sembradas", type=int, default=10)
    a = p.parse_args()
    print("Hojas en:", armar(a.carpeta, a.reales, a.sembradas))
