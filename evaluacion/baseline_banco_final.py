"""Baseline de reglas (sin LLM) sobre el banco final, con el mismo juez y las mismas métricas que Globix.

Corre en local: cada caso del banco pasa por el mismo flujo de /api/eval/caso (`main.ejecutar_caso_eval`), pero
con `ClienteReglas` en lugar del LLM. Después se revisa con los registros del sistema y se califica con el juez
del equipo (`qwen-3.8-27b`, prompts del banco). Las reglas se escribieron antes del banco final.

Uso:
    python evaluacion/baseline_banco_final.py <carpeta Globex_Bancos_V2> [--corrida BASE-REGLAS] [--comparar <corrida de Globix>]

El juez usa las keys de Cerebras del .env local (CEREBRAS_API_KEY y CEREBRAS_API_KEY_RESPALDO, _2…). Reanudable.
Resultados en evaluacion/reportes/banco_final/<corrida>/ (resultado.json y comparacion.json si se compara).
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "evaluacion"))


def _destinos_juez(valores: dict) -> list:
    import juez_banco
    keys = [valores.get("CEREBRAS_API_KEY"), valores.get("CEREBRAS_API_KEY_RESPALDO")] + [
        valores.get(f"CEREBRAS_API_KEY_RESPALDO_{i}") for i in range(2, 21)]
    return [("cerebras", juez_banco.URL, k, juez_banco.MODELO_JUEZ, 20000) for k in dict.fromkeys(k for k in keys if k)]


def comparar(kpis_globix: list, kpis_base: list) -> list:
    """Diferencia por indicador (puntos porcentuales) entre Globix y el baseline."""
    base = {k["indicador"]: k for k in kpis_base}
    filas = []
    for g in kpis_globix:
        b = base.get(g["indicador"])
        if not b:
            continue
        dif = None if g.get("porcentaje") is None or b.get("porcentaje") is None else round(g["porcentaje"] - b["porcentaje"], 1)
        filas.append({"indicador": g["indicador"], "globix": g.get("porcentaje"), "reglas": b.get("porcentaje"),
                      "diferencia_pp": dif, "meta": g.get("meta"), "reglas_cumple": b.get("cumple")})
    return filas


async def _correr(main, cliente, banco: dict, corrida: str, salida: Path) -> list:
    hechos = {}
    if salida.exists():
        for linea in salida.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                fila = json.loads(linea)
                hechos[fila["id"]] = fila
    for i, caso in enumerate(banco["casos"], 1):
        if caso["id"] in hechos:
            continue
        mensajes = caso.get("mensajes") or [caso["pregunta"]]
        fila = await main.ejecutar_caso_eval(corrida, caso["id"], mensajes, caso.get("banco_id"), cliente)
        fila = {**fila, "id": caso["id"], "banco": caso["banco"], "universo": caso.get("universo")}
        hechos[caso["id"]] = fila
        with salida.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
        print(f"  [{i}/{len(banco['casos'])}] {caso['id']} {fila.get('tipo_respuesta')}", flush=True)
    return [hechos[c["id"]] for c in banco["casos"]]


def main_cli():
    p = argparse.ArgumentParser(description="Baseline de reglas sobre el banco final.")
    p.add_argument("banco")
    p.add_argument("--corrida", default="BASE-REGLAS")
    p.add_argument("--comparar", help="carpeta de resultados de Globix (p. ej. BF-1610fbb-x3)")
    a = p.parse_args()
    carpeta = Path(a.banco).resolve()
    destino = RAIZ / "evaluacion" / "reportes" / "banco_final" / a.corrida
    destino.mkdir(parents=True, exist_ok=True)

    from dotenv import dotenv_values
    valores = dotenv_values(RAIZ / ".env")
    # El flujo corre en una carpeta temporal (base SQLite y PDF de prueba) y nunca envía nada a Meta
    os.chdir(tempfile.mkdtemp(prefix="globex_baseline_"))
    os.environ.pop("GLOBEX_DB", None)
    import banco_final
    import juez_banco
    import main
    import revisar_banco_api
    from baseline_reglas import ClienteReglas

    banco, sha = banco_final.verificar_carpeta(carpeta)
    print(f"Banco verificado ({len(banco['casos'])} casos, manifiesto {sha[:16]}…)")
    inicio = time.monotonic()
    filas = asyncio.run(_correr(main, ClienteReglas(), banco, a.corrida, destino / "casos.jsonl"))
    revision = revisar_banco_api.revisar(destino / "casos.jsonl", carpeta, banco.get("ids_bloqueados_productos"))
    juez = juez_banco.Juez(destinos=_destinos_juez(valores))
    resumen_juez = juez_banco.juzgar(filas, carpeta, banco, juez, destino / "juez.jsonl",
                                     ("FAQ", "PRODUCTOS", "CHATS_COMPARTIDOS"), hilos=2)
    kpis = banco_final.calcular_kpis(filas, revision, resumen_juez)
    meta = {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "modelo_chatbot": "reglas (sin LLM)",
            "modelo_juez": juez_banco.MODELO_JUEZ, "sha_manifiesto": sha, "total": len(banco["casos"]),
            "ejecutados": len(filas), "errores": sum(1 for f in filas if f.get("error_ejecucion")),
            "duracion_min": round((time.monotonic() - inicio) / 60, 1),
            "errores_del_juez": resumen_juez.get("errores_del_juez", [])}
    resultado = {"meta": meta, "kpis": kpis, "segmentos": banco_final.segmentos(kpis, banco),
                 "tiempos": banco_final.tiempos(filas)}
    (destino / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Baseline de reglas:")
    for k in kpis:
        print(f"   {k['indicador']}: {k['porcentaje']} % (meta {k['meta']} %)")
    if a.comparar:
        globix = json.loads((RAIZ / "evaluacion" / "reportes" / "banco_final" / a.comparar / "resultado.json")
                            .read_text(encoding="utf-8"))
        comp = comparar(globix["kpis"], kpis)
        (destino / "comparacion.json").write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Globix ({a.comparar}) frente a reglas:")
        for c in comp:
            print(f"   {c['indicador']}: {c['globix']} vs {c['reglas']} → {c['diferencia_pp']:+} pp")


if __name__ == "__main__":
    main_cli()
