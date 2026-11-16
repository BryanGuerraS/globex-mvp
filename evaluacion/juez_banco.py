"""Juez del equipo (system prompts GLOBEX_JUEZ_COMPACTO_1) sobre una corrida de correr_banco_api.py.

Califica caso por caso FAQ, PRODUCTOS y CHATS_COMPARTIDOS (recopilación + resumen) con el prompt del
banco y la ficha de referencia del mismo ID, y calcula los KPI con las fórmulas de los prompts:
FAQ y productos = % aceptables; recopilación = promedio de C/(N+E) por chat; resumen = % aceptables.

Uso:
    python evaluacion/juez_banco.py <corrida.jsonl> <carpeta_del_banco> [--bancos FAQ,PRODUCTOS,CHATS_COMPARTIDOS]

El juez es qwen-3.8-27b en Cerebras (otra familia que Globix), con las keys GRATUITAS del .env
(CEREBRAS_API_KEY_RESPALDO, _2); no usa la key de pago. Resultados en
evaluacion/reportes/bancos_api/JUEZ-<corrida>.jsonl (se puede retomar) y JUEZ-<corrida>.resumen.json.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from metricas import clopper_pearson  # noqa: E402

URL = "https://api.cerebras.ai/v1/chat/completions"
MODELO_JUEZ = "qwen-3.8-27b"
PROMPTS = {"FAQ": "01_Calidad_FAQ.txt", "PRODUCTOS": "03_Productos_Especiales.txt",
           "CHATS_COMPARTIDOS": "07_Chats_Conjunto.txt"}
REFERENCIAS = {"FAQ": ["Referencias.txt"], "PRODUCTOS": ["Referencias.txt"],
               "CHATS_COMPARTIDOS": ["Referencia_Recopilacion.txt", "Referencia_Resumen.txt"]}
CARPETAS = {"FAQ": "01_FAQ", "PRODUCTOS": "03_Productos_Especiales", "CHATS_COMPARTIDOS": "05_Chats_Recopilacion_Resumen"}


def fichas(ruta: Path) -> dict:
    """{id: bloque de texto} de un archivo de referencias (fichas que empiezan con 'ID:')."""
    salida = {}
    for bloque in re.split(r"\n(?=ID:)", ruta.read_text(encoding="utf-8")):
        m = re.search(r"^ID:\s*(\S+)", bloque, re.M)
        if m:
            salida[m.group(1)] = re.sub(r"\n=+\s*$", "", bloque.strip())
    return salida


# Banco final (Globex_Bancos_V2): otros nombres de carpetas y referencias en varios archivos
FINAL = {
    "prompts": "01_System_Prompts",
    "carpetas": {"FAQ": "02_FAQ", "PRODUCTOS": "04_Productos_Especiales",
                 "CHATS_COMPARTIDOS": "05_Chats_Recopilacion_Resumen"},
    "referencias": {"FAQ": {"Referencias.txt": "Respuestas_con_Rubrica/*.txt"},
                    "PRODUCTOS": {"Referencias.txt": "Respuestas_con_Rubrica/*.txt"},
                    "CHATS_COMPARTIDOS": {"Referencia_Recopilacion.txt": "Respuestas_Recopilacion_con_Rubrica.txt",
                                          "Referencia_Resumen.txt": "Respuestas_Resumen_con_Rubrica.txt"}},
}


def referencias_de(carpeta: Path, banco: str, final: bool) -> dict:
    """{nombre que espera el prompt: {id: ficha}} para un banco."""
    if not final:
        return {n: fichas(carpeta / CARPETAS[banco] / n) for n in REFERENCIAS[banco]}
    salida = {}
    for nombre, patron in FINAL["referencias"][banco].items():
        fichas_banco = {}
        for ruta in sorted((carpeta / FINAL["carpetas"][banco]).glob(patron)):
            fichas_banco.update(fichas(ruta))
        salida[nombre] = fichas_banco
    return salida


def caso_compacto(f: dict) -> dict:
    """Un caso de la corrida en el formato GLOBEX_JUEZ_COMPACTO_1."""
    caso = {"id": f["id"], "universo": f.get("universo"),
            "captura": {"estado": "RECIBIDA", "ejecutado": f.get("ejecutado", True),
                        "error_ejecucion": f.get("error_ejecucion")}}
    if f["banco"] != "CHATS_COMPARTIDOS":
        caso.update({"pregunta": f.get("pregunta"), "respuesta": f.get("respuesta_bot"),
                     "mensajes_bot": f.get("respuestas") or [],
                     "tipo_respuesta": f.get("tipo_respuesta"),
                     "bot_pausado": f["registros_acciones"].get("bot_pausado"),
                     "cotizacion": f.get("cotizacion")})
        return caso
    datos = dict(f.get("datos_recopilados") or {})
    datos.pop("cotizacion_aceptada", None)  # excluido del KPI según el prompt
    consola = f["registros_acciones"].get("resumen_en_consola") or {}
    resumen = f.get("resumen_caso") or {}
    textos = []
    for t in (consola.get("texto"), resumen.get("texto")):
        if isinstance(t, str) and t and t not in textos:
            textos.append(t)

    def fuente(publicado, texto):
        if isinstance(texto, str) and texto:
            return {"publicado": publicado, "texto_ref": textos.index(texto)}
        return {"publicado": publicado, "texto": texto}

    caso.update({
        "conversacion": [{"mensaje": t["mensaje"], "respuesta_bot": t["respuesta_bot"],
                          "tipo_respuesta": t["tipo_respuesta"]} for t in f.get("turnos", [])],
        "datos_recopilados": datos,
        "resumen": {"textos": textos, "consola": fuente(consola.get("publicado"), consola.get("texto")),
                    "caso": fuente(resumen.get("publicado"), resumen.get("texto"))},
        "bot_pausado": f["registros_acciones"].get("bot_pausado"),
        "cotizacion": f.get("cotizacion"),
    })
    return caso


def entrada(f: dict, banco_json: dict, refs: dict) -> str:
    previstos = [c["id"] for c in banco_json["casos"] if c["banco"] == f["banco"]]
    resultados = {
        "formato": "GLOBEX_JUEZ_COMPACTO_1", "banco": f["banco"], "banco_id": f.get("banco_id"),
        "version_banco": banco_json.get("version_paquete"), "corrida_id": f.get("corrida_id"),
        "commit_chatbot": (f.get("control_versiones") or {}).get("commit_chatbot"),
        "ids_previstos": previstos, "ids_seleccionados": [f["id"]], "seleccion_cubre_banco_completo": False,
        "casos": [caso_compacto(f)],
    }
    if f["banco"] == "PRODUCTOS":
        resultados["ids_bloqueados_previstos"] = banco_json.get("ids_bloqueados_productos", [])
    partes = [f"Resultados.json:\n{json.dumps(resultados, ensure_ascii=False, indent=1)}"]
    for nombre, bloques in refs.items():
        partes.append(f"{nombre} (ficha del caso {f['id']}):\n{bloques.get(f['id'], '(sin ficha)')}")
    return "\n\n".join(partes)


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELO_JUEZ = "qwen/qwen3.8-27b"


def destinos_locales(valores: dict, proveedor: str = "mixto") -> list:
    """Juez FUERA del endpoint (decisión del usuario 16/11): keys de Groq y/o las gratuitas de Cerebras.
    Groq primero (más cupo diario); si una llamada no cabe en su límite por minuto, pasa a Cerebras."""
    destinos = []
    if proveedor in ("groq", "mixto"):
        groq = [valores.get("GROQ_API_KEY_JUEZ"), valores.get("GROQ_API_KEY")] + [
            valores.get(f"GROQ_API_KEY_RESPALDO{'' if i == 1 else f'_{i}'}") for i in range(1, 21)]
        destinos += [("groq", GROQ_URL, k, GROQ_MODELO_JUEZ, 6000) for k in dict.fromkeys(g for g in groq if g)]
    if proveedor in ("cerebras", "mixto"):
        gratuitas = [valores.get("CEREBRAS_API_KEY_RESPALDO")] + [
            valores.get(f"CEREBRAS_API_KEY_RESPALDO_{i}") for i in range(2, 21)]
        destinos += [("cerebras", URL, k, MODELO_JUEZ, 20000) for k in gratuitas if k]
    return destinos


def destinos_pago(entorno) -> list:
    """Juez del endpoint (ejecución oficial): la key de PAGO de Cerebras. JUEZ_CEREBRAS_API_KEY si está;
    si no, la última key de Cerebras configurada (en Render la de pago va al final)."""
    key = entorno.get("JUEZ_CEREBRAS_API_KEY")
    if not key:
        keys = [entorno.get("CEREBRAS_API_KEY")] + [
            entorno.get(f"CEREBRAS_API_KEY_RESPALDO{'' if i == 1 else f'_{i}'}") for i in range(1, 21)]
        keys = [k for k in keys if k]
        key = keys[-1] if keys else None
    return [("cerebras", URL, key, MODELO_JUEZ, 20000)] if key else []


class Juez:
    def __init__(self, destinos: list = None, proveedor: str = "mixto"):
        """destinos: [(proveedor, url, key, modelo, max_tokens), ...] en orden de preferencia."""
        self.destinos = destinos if destinos is not None else destinos_locales(dotenv_values(RAIZ / ".env"), proveedor)
        if not self.destinos:
            raise RuntimeError("No hay keys para el juez")
        self.pausa = [0.0] * len(self.destinos)
        self.http = httpx.Client(timeout=300)
        self.usados = {}

    def __call__(self, sistema: str, usuario: str) -> str:
        """Razonamiento medio; si se le acaban los tokens antes de responder, se reintenta en bajo."""
        texto = self._llamar(sistema, usuario, "medium")
        return texto if texto else self._llamar(sistema, usuario, "low")

    def _llamar(self, sistema: str, usuario: str, esfuerzo: str) -> str:
        grande = set()  # destinos donde esta llamada no cabe (límite por minuto de Groq)
        for _ in range(80):
            ahora = time.monotonic()
            libres = [i for i, p in enumerate(self.pausa) if p <= ahora and i not in grande]
            if not libres:
                pendientes = [p for i, p in enumerate(self.pausa) if i not in grande and p != float("inf")]
                if not pendientes:
                    raise RuntimeError("ninguna key del juez puede atender esta llamada")
                time.sleep(max(min(pendientes) - ahora, 1))
                continue
            i = libres[0]
            proveedor, url, key, modelo, max_tokens = self.destinos[i]
            r = self.http.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                "model": modelo, "temperature": 0, "max_tokens": max_tokens, "reasoning_effort": esfuerzo,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
            if r.status_code in (401, 402, 403):  # key sin créditos o revocada: se aparta
                self.pausa[i] = float("inf")
                continue
            if r.status_code == 413 or (r.status_code == 400 and "too large" in r.text.lower()):
                grande.add(i)  # la llamada supera lo que admite esta key por minuto
                continue
            if r.status_code == 429:
                espera = float(r.headers.get("retry-after") or 60)
                if proveedor == "groq" and "tokens per day" in r.text:
                    espera = max(espera, 3600)
                self.pausa[i] = time.monotonic() + espera
                continue
            if r.status_code >= 500:
                time.sleep(10)
                continue
            r.raise_for_status()
            self.usados[proveedor] = self.usados.get(proveedor, 0) + 1
            return r.json()["choices"][0]["message"].get("content") or ""
        raise RuntimeError("el juez no respondió tras varios intentos")


def json_de(texto: str) -> dict:
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S)
    inicio, fin = texto.find("{"), texto.rfind("}")
    return json.loads(texto[inicio:fin + 1])


def _primero(d: dict, clave: str):
    """El primer caso de d[clave]['casos'] o de d['casos']."""
    bloque = d.get(clave, d) if clave else d
    casos = bloque.get("casos") or []
    return casos[0] if casos else {}


def resumir(salida: Path) -> dict:
    filas = [json.loads(l) for l in salida.read_text(encoding="utf-8").splitlines() if l.strip()]
    r = {}
    for banco in ("FAQ", "PRODUCTOS"):
        casos = [_primero(f["veredicto"], None) for f in filas if f["banco"] == banco and "veredicto" in f]
        decididos = [c for c in casos if isinstance(c.get("aceptable"), bool)]
        ok = sum(c["aceptable"] for c in decididos)
        r[banco] = {"aceptables": ok, "decididos": len(decididos), "casos": len(casos),
                    "porcentaje": round(100 * ok / len(decididos), 2) if decididos else None,
                    "ic95": clopper_pearson(ok, len(decididos)) if decididos else None,
                    "no_aceptables": [c.get("id") for c in decididos if not c["aceptable"]]}
        if banco == "PRODUCTOS":
            r[banco]["avances_indebidos"] = [c.get("id") for c in casos if c.get("avance_indebido_a_cotizacion") is True]
    chats = [f for f in filas if f["banco"] == "CHATS_COMPARTIDOS" and "veredicto" in f]
    pct = [c["porcentaje"] for c in (_primero(f["veredicto"], "recopilacion") for f in chats)
           if isinstance(c.get("porcentaje"), (int, float))]
    res = [_primero(f["veredicto"], "resumen") for f in chats]
    res_ok = [c for c in res if isinstance(c.get("aceptable_para_kpi"), bool)]
    r["RECOPILACION"] = {"chats": len(chats), "evaluados": len(pct),
                         "promedio_porcentaje": round(sum(pct) / len(pct), 2) if pct else None}
    r["RESUMEN"] = {"aceptables": sum(c["aceptable_para_kpi"] for c in res_ok), "decididos": len(res_ok),
                    "porcentaje": round(100 * sum(c["aceptable_para_kpi"] for c in res_ok) / len(res_ok), 2)
                    if res_ok else None,
                    "no_aceptables": [c.get("id") for c in res_ok if not c["aceptable_para_kpi"]]}
    r["errores_del_juez"] = [f["id"] for f in filas if "error" in f]
    return r


def juzgar(filas: list, carpeta: Path, banco_json: dict, juez: "Juez", salida: Path,
           bancos=("FAQ", "PRODUCTOS", "CHATS_COMPARTIDOS"), hilos: int = 1, avance=None) -> dict:
    """Califica las filas de una corrida (formato de /api/eval/caso) y devuelve el resumen de KPI.

    Escribe una línea por caso en `salida` (se puede retomar: salta los ids ya calificados). `hilos` > 1
    califica en paralelo (para la key de pago). `avance(hechos, total)` se llama tras cada caso.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    final = (carpeta / FINAL["prompts"]).exists()
    hechos = set()
    if salida.exists():
        hechos = {json.loads(l)["id"] for l in salida.read_text(encoding="utf-8").splitlines()
                  if l.strip() and "veredicto" in json.loads(l)}
    tareas = []
    for banco in bancos:
        sistema = (carpeta / (FINAL["prompts"] if final else "06_System_Prompts") / PROMPTS[banco]).read_text(encoding="utf-8")
        refs = referencias_de(carpeta, banco, final)
        sin_ficha = [f["id"] for f in filas if f["banco"] == banco and not any(f["id"] in r for r in refs.values())]
        if sin_ficha:
            print(f"AVISO {banco}: casos sin ficha de referencia: {sin_ficha}", flush=True)
        tareas += [(banco, sistema, refs, f) for f in filas if f["banco"] == banco and f["id"] not in hechos]
    candado, contador = Lock(), [0]

    def calificar(tarea):
        banco, sistema, refs, f = tarea
        fila = {"id": f["id"], "banco": banco, "modelo_juez": MODELO_JUEZ}
        try:
            fila["veredicto"] = json_de(juez(sistema, entrada(f, banco_json, refs)))
        except Exception as e:  # noqa: BLE001  (se registra y se puede retomar)
            fila["error"] = f"{e.__class__.__name__}: {str(e)[:200]}"
        with candado:
            with salida.open("a", encoding="utf-8") as out:
                out.write(json.dumps(fila, ensure_ascii=False) + "\n")
            contador[0] += 1
            print(f"[{banco} {contador[0]}/{len(tareas)}] {f['id']} "
                  f"{'ERROR ' + fila['error'] if 'error' in fila else 'ok'}", flush=True)
            if avance:
                avance(contador[0], len(tareas))

    with ThreadPoolExecutor(max_workers=max(1, hilos)) as pool:
        list(pool.map(calificar, tareas))
    resumen = resumir(salida)
    salida.with_suffix(".resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("corrida")
    p.add_argument("banco_carpeta")
    p.add_argument("--bancos", default="FAQ,PRODUCTOS,CHATS_COMPARTIDOS")
    p.add_argument("--banco-json", help="JSON de ejecución (por defecto el del banco de desarrollo)")
    p.add_argument("--juez", choices=["mixto", "groq", "cerebras"], default="mixto",
                   help="Keys del juez fuera del endpoint: Groq y/o las gratuitas de Cerebras (nunca la de pago)")
    a = p.parse_args()
    carpeta = Path(a.banco_carpeta)
    corrida = Path(a.corrida)
    ruta_json = Path(a.banco_json) if a.banco_json else carpeta / "Banco_Desarrollo_Ejecucion.json"
    banco_json = json.loads(ruta_json.read_text(encoding="utf-8"))
    filas = [json.loads(l) for l in corrida.read_text(encoding="utf-8").splitlines() if l.strip()]
    salida = corrida.with_name(f"JUEZ-{corrida.stem}.jsonl")
    resumen = juzgar(filas, carpeta, banco_json, Juez(proveedor=a.juez), salida, a.bancos.split(","))
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
