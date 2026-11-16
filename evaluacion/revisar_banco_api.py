"""Revisión automática de una corrida de banco (correr_banco_api.py) contra sus referencias.

Mide lo que no necesita juez: total de cotizaciones al centavo, derivación (bot pausado) y avances
indebidos a cotización en productos bloqueados. FAQ, respuestas de productos y chats van al juez.

Uso: python evaluacion/revisar_banco_api.py <corrida.jsonl> <carpeta_del_banco>
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metricas import clopper_pearson  # noqa: E402


def _bloques(ruta: Path):
    texto = ruta.read_text(encoding="utf-8")
    for bloque in re.split(r"\n=+\n", texto):
        m = re.search(r"^ID:\s*(\S+)", bloque, re.M)
        if m:
            yield m.group(1), bloque


def referencias(carpeta: Path) -> dict:
    ref = {}
    for ruta in carpeta.rglob("Referencias.txt"):
        for cid, bloque in _bloques(ruta):
            r = ref.setdefault(cid, {})
            m = re.search(r"TOTAL ESPERADO:\s*USD\s*([\d.,]+)", bloque)
            if m:
                r["total"] = float(m.group(1).replace(",", ""))
            if re.search(r"REQUIERE DERIVACIÓN:\s*SÍ", bloque):
                r["deriva"] = True
            m = re.search(r"COTIZACIÓN BLOQUEADA:\s*(SÍ|NO)", bloque)
            if m:
                r["bloqueada"] = m.group(1) == "SÍ"
            m = re.search(r"^CONDICIÓN:\s*(\S+)", bloque, re.M)
            if m:
                r["condicion"] = m.group(1)
    return ref


def revisar(corrida: Path, carpeta: Path) -> dict:
    filas = [json.loads(l) for l in corrida.read_text(encoding="utf-8").splitlines() if l.strip()]
    ref = referencias(carpeta)
    salida = {"casos": len(filas), "errores_ejecucion": [f["id"] for f in filas if f.get("error_ejecucion")]}

    cot = [(f, ref[f["id"]]) for f in filas if f["id"] in ref and "total" in ref[f["id"]]]
    mal_cot = [{"id": f["id"], "esperado": r["total"], "obtenido": (f.get("cotizacion") or {}).get("total_proforma"),
                "tipo": f.get("tipo_respuesta")}
               for f, r in cot if (f.get("cotizacion") or {}).get("total_proforma") is None
               or abs(f["cotizacion"]["total_proforma"] - r["total"]) > 0.001]
    salida["cotizaciones"] = {"correctas": len(cot) - len(mal_cot), "n": len(cot),
                              "ic95": clopper_pearson(len(cot) - len(mal_cot), len(cot)), "fallas": mal_cot}

    der = [(f, ref[f["id"]]) for f in filas if ref.get(f["id"], {}).get("deriva")]
    mal_der = [{"id": f["id"], "tipo": f.get("tipo_respuesta")} for f, _ in der
               if not f["registros_acciones"]["bot_pausado"]]
    salida["derivacion_efectiva"] = {"derivadas": len(der) - len(mal_der), "n": len(der),
                                     "ic95": clopper_pearson(len(der) - len(mal_der), len(der)), "fallas": mal_der}

    bloq = [(f, ref[f["id"]]) for f in filas if ref.get(f["id"], {}).get("bloqueada")]
    indebidos = [{"id": f["id"], "condicion": r.get("condicion")} for f, r in bloq
                 if (f.get("cotizacion") or {}).get("emitida")]
    salida["productos_bloqueados"] = {"sin_avance_indebido": len(bloq) - len(indebidos), "n": len(bloq),
                                      "avances_indebidos": indebidos}
    no_bloq = [(f, ref[f["id"]]) for f in filas if ref.get(f["id"], {}).get("bloqueada") is False]
    salida["productos_no_bloqueados"] = [{"id": f["id"], "condicion": r.get("condicion"),
                                          "tipo": f.get("tipo_respuesta"),
                                          "cotizo": (f.get("cotizacion") or {}).get("emitida"),
                                          "pausado": f["registros_acciones"]["bot_pausado"]} for f, r in no_bloq]
    return salida


if __name__ == "__main__":
    print(json.dumps(revisar(Path(sys.argv[1]), Path(sys.argv[2])), ensure_ascii=False, indent=2))
