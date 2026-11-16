"""Corre un banco del equipo (formato GLOBEX_BANCO_EJECUCION_1) contra la API de evaluación de Render.

Uso:
    python evaluacion/correr_banco_api.py <banco.json> [--corrida ID] [--solo ID1,ID2] [--url URL]

Cada caso va a POST /api/eval/caso (sesión nueva, Cerebras). Guarda una línea JSON por caso en
evaluacion/reportes/bancos_api/<corrida>.jsonl y, al final, GET /api/eval/resumen. Lee
EVAL_API_KEY del .env sin imprimirla. Reintenta ante 429 o errores del servidor.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
URL_RENDER = "https://globex-mvp.onrender.com"


def correr(banco: Path, corrida: str, solo=None, url: str = URL_RENDER) -> Path:
    load_dotenv(RAIZ / ".env")
    key = os.environ.get("EVAL_API_KEY")
    if not key:
        sys.exit("Falta EVAL_API_KEY en el .env")
    datos = json.loads(banco.read_text(encoding="utf-8"))
    casos = [c for c in datos["casos"] if not solo or c["id"] in solo]
    salida = RAIZ / "evaluacion" / "reportes" / "bancos_api" / f"{corrida}.jsonl"
    salida.parent.mkdir(parents=True, exist_ok=True)
    hechos = set()
    if salida.exists():  # se puede retomar una corrida cortada
        hechos = {json.loads(l)["id"] for l in salida.read_text(encoding="utf-8").splitlines() if l.strip()}
    with httpx.Client(timeout=240) as http, salida.open("a", encoding="utf-8") as f:
        for i, caso in enumerate(casos, 1):
            if caso["id"] in hechos:
                continue
            cuerpo = {"banco_id": caso.get("banco_id"), "corrida_id": corrida, "id": caso["id"]}
            cuerpo.update({"mensajes": caso["mensajes"]} if caso.get("mensajes") else {"pregunta": caso["pregunta"]})
            for intento in range(6):
                try:
                    r = http.post(f"{url}/api/eval/caso", headers={"X-API-Key": key}, json=cuerpo)
                except httpx.HTTPError as e:
                    print(f"  red: {e.__class__.__name__}, reintento")
                    time.sleep(10)
                    continue
                if r.status_code == 200:
                    break
                print(f"  {caso['id']}: HTTP {r.status_code}, reintento")
                time.sleep(20 if r.status_code == 429 else 10)
            else:
                print(f"[{i}/{len(casos)}] {caso['id']} SIN RESPUESTA")
                continue
            fila = {**r.json(), "banco": caso["banco"], "universo": caso.get("universo")}
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(casos)}] {caso['id']} {fila.get('tipo_respuesta')} "
                  f"{'ERROR ' + fila['error_ejecucion'] if fila.get('error_ejecucion') else ''}")
        resumen = http.get(f"{url}/api/eval/resumen", headers={"X-API-Key": key}, params={"corrida_id": corrida})
    if resumen.status_code == 200:
        (salida.with_suffix(".resumen.json")).write_text(json.dumps(resumen.json(), ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    print(f"Resultados: {salida}")
    return salida


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("banco")
    p.add_argument("--corrida", default=datetime.now().strftime("DEV-%m%d-%H%M"))
    p.add_argument("--solo")
    p.add_argument("--url", default=URL_RENDER)
    a = p.parse_args()
    correr(Path(a.banco), a.corrida, set(a.solo.split(",")) if a.solo else None, a.url)
