"""Evaluación de Globix con el banco final: un comando, informe en PDF.

    pip install -r requirements-evaluacion.txt
    python evaluacion.py <carpeta Globex_Bancos_V2>

Qué hace (opción B, decisión del equipo 16/11):
1. Verifica cada archivo del banco contra su MANIFIESTO_SHA256.txt.
2. Envía cada caso a Globix en Render (POST /api/eval/caso): mismo flujo que WhatsApp, sin enviar nada a Meta.
   Los resultados se guardan uno por uno; si algo se corta, al volver a ejecutar continúa donde quedó.
3. Revisa con los registros del sistema la derivación, el total cotizado y las cotizaciones a pedidos bloqueados.
4. Califica FAQ, productos y chats con el juez del equipo (prompts del banco) a través de Render
   (POST /api/eval/juzgar, con la key de pago del servidor): aquí no hace falta ninguna key de LLM.
5. Genera el informe en PDF (y un JSON con los indicadores) en evaluacion/reportes/banco_final/<corrida>/.

Solo necesita la clave de evaluación: variable EVAL_API_KEY (o en un archivo .env).
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

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "evaluacion"))
import banco_final  # noqa: E402
import juez_banco  # noqa: E402
import revisar_banco_api  # noqa: E402
from informe_banco_final_pdf import generar as generar_pdf  # noqa: E402

URL = "https://globex-mvp.onrender.com"


class Servidor:
    """Llamadas a Render con reintentos: el plan gratuito puede tardar en despertar o reiniciarse."""

    def __init__(self, url: str, key: str):
        self.url, self.http = url.rstrip("/"), httpx.Client(timeout=300, headers={"X-API-Key": key})

    def post(self, ruta: str, cuerpo: dict) -> dict:
        espera = 10
        for intento in range(12):
            try:
                r = self.http.post(self.url + ruta, json=cuerpo)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (401, 403, 422):
                    sys.exit(f"El servidor rechazó la llamada ({r.status_code}): {r.text[:200]}")
                motivo = f"HTTP {r.status_code}"
            except (httpx.HTTPError, ValueError) as e:
                motivo = e.__class__.__name__
            print(f"    reintento {intento + 1} en {espera} s ({motivo})", flush=True)
            time.sleep(espera)
            espera = min(espera * 2, 120)
        raise RuntimeError(f"El servidor no respondió a {ruta} tras varios reintentos")


class JuezRemoto:
    """El juez del equipo, ejecutado en Render con la key de pago."""

    def __init__(self, servidor: Servidor):
        self.servidor = servidor

    def __call__(self, sistema: str, usuario: str) -> str:
        return self.servidor.post("/api/eval/juzgar", {"sistema": sistema, "usuario": usuario})["respuesta"]


def correr_casos(servidor: Servidor, banco: dict, corrida: str, salida: Path) -> list:
    hechos = {}
    if salida.exists():
        for linea in salida.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                fila = json.loads(linea)
                hechos[fila["id"]] = fila
    casos = banco["casos"]
    for i, caso in enumerate(casos, 1):
        if caso["id"] in hechos:
            continue
        cuerpo = {"banco_id": caso.get("banco_id"), "corrida_id": corrida, "id": caso["id"],
                  **({"mensajes": caso["mensajes"]} if caso.get("mensajes") else {"pregunta": caso["pregunta"]})}
        fila = {**servidor.post("/api/eval/caso", cuerpo), "banco": caso["banco"], "universo": caso.get("universo")}
        hechos[caso["id"]] = fila
        with salida.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
        print(f"  [{i}/{len(casos)}] {caso['id']} {fila.get('tipo_respuesta')}", flush=True)
    return [hechos[c["id"]] for c in casos]


def main():
    p = argparse.ArgumentParser(description="Evalúa Globix con el banco final y genera el informe en PDF.")
    p.add_argument("banco", help="carpeta Globex_Bancos_V2 (con 00_Indice_Bancos.txt y MANIFIESTO_SHA256.txt)")
    p.add_argument("--url", default=os.environ.get("GLOBIX_URL", URL))
    p.add_argument("--corrida", help="nombre de la corrida; repetirlo continúa una corrida cortada")
    a = p.parse_args()
    load_dotenv(RAIZ / ".env")
    key = os.environ.get("EVAL_API_KEY")
    if not key:
        sys.exit("Falta EVAL_API_KEY (variable de entorno o archivo .env).")
    carpeta = Path(a.banco)
    inicio = time.monotonic()

    print("1. Verificando el banco contra su manifiesto…")
    try:
        banco, sha = banco_final.verificar_carpeta(carpeta)
    except banco_final.BancoInvalido as e:
        sys.exit(f"Banco no válido: {e}")
    print(f"   {len(banco['casos'])} casos · manifiesto {sha[:16]}… verificado")

    corrida = a.corrida or datetime.now().strftime("BF-%m%d-%H%M")
    destino = RAIZ / "evaluacion" / "reportes" / "banco_final" / corrida
    destino.mkdir(parents=True, exist_ok=True)
    servidor = Servidor(a.url, key)

    print(f"2. Ejecutando los casos en Globix ({a.url})…")
    filas = correr_casos(servidor, banco, corrida, destino / "casos.jsonl")

    print("3. Revisando derivación, totales y pedidos bloqueados…")
    revision = revisar_banco_api.revisar(destino / "casos.jsonl", carpeta, banco.get("ids_bloqueados_productos"))

    print("4. Calificando con el juez del equipo (en el servidor, key de pago)…")
    juez = juez_banco.juzgar(filas, carpeta, banco, JuezRemoto(servidor), destino / "juez.jsonl",
                             ("FAQ", "PRODUCTOS", "CHATS_COMPARTIDOS"), hilos=4)

    print("5. Generando el informe…")
    # Duración acumulada: al reanudar con --corrida se suma a la de las ejecuciones anteriores
    archivo_duracion = destino / "duracion_s.txt"
    previa = float(archivo_duracion.read_text(encoding="utf-8")) if archivo_duracion.exists() else 0.0
    duracion_s = previa + (time.monotonic() - inicio)
    archivo_duracion.write_text(f"{duracion_s:.1f}", encoding="utf-8")
    indice = json.loads((carpeta / "00_Indice_Bancos.txt").read_text(encoding="utf-8"))
    kpis = banco_final.calcular_kpis(filas, revision, juez, indice)
    commits = {(f.get("control_versiones") or {}).get("commit_chatbot") for f in filas} - {None}
    meta = {
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "commit": ", ".join(sorted(c[:7] for c in commits)) or None,
        "modelo_chatbot": "Cerebras gpt-oss-120b",
        "version_banco": banco.get("version_paquete"), "sha_manifiesto": sha,
        "modelo_juez": juez_banco.MODELO_JUEZ, "total": len(banco["casos"]), "ejecutados": len(filas),
        "errores": sum(1 for f in filas if f.get("error_ejecucion")),
        "duracion_min": round(duracion_s / 60, 1),
        "errores_del_juez": juez.get("errores_del_juez", []),
    }
    (destino / "resultado.json").write_text(json.dumps(
        {"meta": meta, "kpis": kpis, "tiempos": banco_final.tiempos(filas)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    pdf = generar_pdf(destino, destino / f"Informe_final_{corrida}.pdf")
    for k in kpis:
        estado = "cumple" if k["cumple"] else "no cumple"
        valor = "—" if k["porcentaje"] is None else f"{k['porcentaje']:.1f} %"
        print(f"   {k['indicador']}: {valor} (meta {k['meta']} %) → {estado}")
    print(f"Informe: {pdf}")


if __name__ == "__main__":
    main()
