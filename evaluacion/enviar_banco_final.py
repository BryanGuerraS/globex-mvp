"""Lanza la corrida del banco final en el servidor y descarga el informe recién generado.

Uso:
    python evaluacion/enviar_banco_final.py <carpeta Globex_Bancos_V2> [--url URL] [--salida carpeta]

Comprime la carpeta del banco, la envía a POST /api/eval/banco-final (el servidor verifica el manifiesto),
consulta el avance cada 30 s y, al terminar, guarda informe.md, resultado.json, resultados (casos) y juez
en la carpeta de salida. Lee EVAL_API_KEY del entorno o del .env (no la imprime).
"""

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
URL_RENDER = "https://globex-mvp.onrender.com"


def comprimir(carpeta: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta in carpeta.rglob("*"):
            if ruta.is_file():
                z.write(ruta, f"{carpeta.name}/{ruta.relative_to(carpeta).as_posix()}")
    return buf.getvalue()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("carpeta")
    p.add_argument("--url", default=URL_RENDER)
    p.add_argument("--salida", default=str(RAIZ / "evaluacion" / "reportes" / "banco_final_endpoint"))
    a = p.parse_args()
    load_dotenv(RAIZ / ".env")
    key = os.environ.get("EVAL_API_KEY")
    if not key:
        sys.exit("Falta EVAL_API_KEY")
    cabeceras = {"X-API-Key": key}
    with httpx.Client(timeout=300) as http:
        r = http.post(f"{a.url}/api/eval/banco-final", headers={**cabeceras, "Content-Type": "application/zip"},
                      content=comprimir(Path(a.carpeta)))
        if r.status_code != 202:
            sys.exit(f"El servidor no aceptó el banco: HTTP {r.status_code} {r.text[:300]}")
        trabajo = r.json()["trabajo_id"]
        print(f"Trabajo {trabajo}: {r.json()['casos']} casos, manifiesto {r.json()['sha_manifiesto'][:16]}…")
        while True:
            time.sleep(30)
            try:
                estado = http.get(f"{a.url}/api/eval/banco-final/{trabajo}", headers=cabeceras).json()
            except httpx.HTTPError as e:
                print(f"  (sin respuesta: {e.__class__.__name__}; reintento)")
                continue
            print(f"  {estado.get('fase')}: casos {estado.get('casos_hechos')}/{estado.get('casos_total')}"
                  f" · juez {estado.get('juez_hechos')}/{estado.get('juez_total') or '?'}", flush=True)
            if estado.get("estado") != "en_curso":
                break
        if estado.get("estado") != "listo":
            sys.exit(f"La corrida terminó con error: {estado.get('error')}")
        salida = Path(a.salida) / trabajo
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "informe.md").write_text(
            http.get(f"{a.url}/api/eval/banco-final/{trabajo}/informe", headers=cabeceras).text, encoding="utf-8")
        (salida / "resultado.json").write_text(json.dumps(estado["resultado"], ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        for tipo in ("casos", "juez"):
            (salida / f"{tipo}.jsonl").write_bytes(http.get(
                f"{a.url}/api/eval/banco-final/{trabajo}/resultados", headers=cabeceras, params={"tipo": tipo}).content)
        print(f"Informe en {salida / 'informe.md'}")


if __name__ == "__main__":
    main()
