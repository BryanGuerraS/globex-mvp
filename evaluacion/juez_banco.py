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
    """{id: bloque de texto} de un archivo de referencias (bloques separados por líneas de '=')."""
    salida = {}
    for bloque in re.split(r"\n=+\n", ruta.read_text(encoding="utf-8")):
        m = re.search(r"^ID:\s*(\S+)", bloque, re.M)
        if m:
            salida[m.group(1)] = bloque.strip()
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


class Juez:
    def __init__(self):
        valores = dotenv_values(RAIZ / ".env")
        self.keys = [k for k in (valores.get("CEREBRAS_API_KEY_RESPALDO"), valores.get("CEREBRAS_API_KEY_RESPALDO_2")) if k]
        if not self.keys:
            sys.exit("Faltan las keys gratuitas de Cerebras en el .env")
        self.pausa = [0.0] * len(self.keys)
        self.http = httpx.Client(timeout=300)

    def __call__(self, sistema: str, usuario: str) -> str:
        """Razonamiento medio; si se le acaban los tokens antes de responder, se reintenta en bajo."""
        texto = self._llamar(sistema, usuario, "medium")
        return texto if texto else self._llamar(sistema, usuario, "low")

    def _llamar(self, sistema: str, usuario: str, esfuerzo: str) -> str:
        for _ in range(40):
            ahora = time.monotonic()
            libres = [i for i, p in enumerate(self.pausa) if p <= ahora]
            if not libres:
                time.sleep(max(min(self.pausa) - ahora, 1))
                continue
            i = libres[0]
            r = self.http.post(URL, headers={"Authorization": f"Bearer {self.keys[i]}"}, json={
                "model": MODELO_JUEZ, "temperature": 0, "max_tokens": 20000, "reasoning_effort": esfuerzo,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
            if r.status_code in (401, 402, 403):  # key sin créditos o revocada: se aparta
                self.pausa[i] = float("inf")
                if all(p == float("inf") for p in self.pausa):
                    raise RuntimeError("ninguna key gratuita de Cerebras tiene créditos")
                continue
            if r.status_code == 429:
                self.pausa[i] = time.monotonic() + float(r.headers.get("retry-after") or 60)
                continue
            if r.status_code >= 500:
                time.sleep(10)
                continue
            r.raise_for_status()
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("corrida")
    p.add_argument("banco_carpeta")
    p.add_argument("--bancos", default="FAQ,PRODUCTOS,CHATS_COMPARTIDOS")
    a = p.parse_args()
    carpeta = Path(a.banco_carpeta)
    corrida = Path(a.corrida)
    banco_json = json.loads((carpeta / "Banco_Desarrollo_Ejecucion.json").read_text(encoding="utf-8"))
    filas = [json.loads(l) for l in corrida.read_text(encoding="utf-8").splitlines() if l.strip()]
    salida = corrida.with_name(f"JUEZ-{corrida.stem}.jsonl")
    hechos = set()
    if salida.exists():
        hechos = {json.loads(l)["id"] for l in salida.read_text(encoding="utf-8").splitlines()
                  if l.strip() and "veredicto" in json.loads(l)}
    juez = Juez()
    bancos = a.bancos.split(",")
    for banco in bancos:
        sistema = (carpeta / "06_System_Prompts" / PROMPTS[banco]).read_text(encoding="utf-8")
        refs = {n: fichas(carpeta / CARPETAS[banco] / n) for n in REFERENCIAS[banco]}
        casos = [f for f in filas if f["banco"] == banco and f["id"] not in hechos]
        for i, f in enumerate(casos, 1):
            fila = {"id": f["id"], "banco": banco, "modelo_juez": MODELO_JUEZ}
            try:
                fila["veredicto"] = json_de(juez(sistema, entrada(f, banco_json, refs)))
            except Exception as e:  # noqa: BLE001  (se registra y se puede retomar)
                fila["error"] = f"{e.__class__.__name__}: {str(e)[:200]}"
            with salida.open("a", encoding="utf-8") as out:
                out.write(json.dumps(fila, ensure_ascii=False) + "\n")
            print(f"[{banco} {i}/{len(casos)}] {f['id']} {'ERROR ' + fila['error'] if 'error' in fila else 'ok'}",
                  flush=True)
    resumen = resumir(salida)
    salida.with_suffix(".resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
