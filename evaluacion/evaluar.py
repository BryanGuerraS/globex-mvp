"""Evaluación de Globix con el LLM real, sin WhatsApp.

Corre cada caso de un archivo JSON varias veces contra el flujo real
(`procesar_mensaje_consolidado`), con Meta bloqueado y una base de datos
temporal, y genera:
- un reporte Markdown para depurar (KPIs con IC de Clopper-Pearson, costo y
  latencia, tabla por caso y, para cada falla, la conversación completa con
  herramientas, argumentos, tokens y tiempos);
- un JSON con todos los datos crudos.

Uso (desde la raíz del repo):
    python evaluacion/evaluar.py
    python evaluacion/evaluar.py --casos evaluacion/casos_reservados.json --repeticiones 3
    python evaluacion/evaluar.py --solo COT-01,ALC-02 --repeticiones 1

Necesita GROQ_API_KEY en el .env (consume tokens de Groq; el set de desarrollo
con 3 repeticiones cuesta del orden de centavos de dólar).
"""

import argparse
import asyncio
import json
import math
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime

if __package__ in (None, ""):  # ejecutado como script: python evaluacion/evaluar.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluacion.reporte_pdf import generar_reporte_pdf  # noqa: E402
from metricas import clopper_pearson  # noqa: E402,F401
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBOUNCE_S = 5.0  # espera fija del webhook antes de procesar (no se simula aquí)
NOMBRE_CLIENTE = "Cliente Evaluación"  # no parece un nombre real: no personaliza


# ---------------------------------------------------------------- Estadística

# clopper_pearson vive en metricas.py (lo usa también el KPI de atención)


def proporcion(exitos: int, n: int) -> Dict:
    li, ls = clopper_pearson(exitos, n)
    return {"exitos": exitos, "n": n, "valor": (exitos / n) if n else None, "ic95": [li, ls]}


# ---------------------------------------------------------------- Verificaciones

def _tipo_coincide(tipo: Optional[str], permitidos: List[str]) -> bool:
    if tipo is None:
        return False
    # "pide_dato" es una respuesta libre que pide un dato indispensable (KPI del E3)
    partes = ["libre" if t == "pide_dato" else t for t in tipo.split("+")] + tipo.split("+")
    return any(tipo == p or tipo.startswith(p + ":") or p in partes for p in permitidos)


def evaluar_corrida(caso: Dict, corrida: Dict) -> List[Dict]:
    """Compara una corrida con lo esperado. Devuelve una lista de verificaciones."""
    esp = caso.get("esperado", {})
    procesados = [t for t in corrida["turnos"] if not t.get("silenciado")]
    ultimo = procesados[-1] if procesados else {}
    herramientas = [h for t in procesados for h in t.get("herramientas", [])]
    nombres = [h["nombre"] for h in herramientas]
    textos_bot = "\n".join(r for t in corrida["turnos"] for r in t.get("respuestas", []))
    checks: List[Dict] = []

    def check(nombre, ok, detalle=""):
        checks.append({"check": nombre, "ok": bool(ok), "detalle": detalle})

    if "tipo_final" in esp:
        tipo = ultimo.get("tipo_respuesta")
        check("tipo_final", _tipo_coincide(tipo, esp["tipo_final"]),
              f"obtenido={tipo!r}, esperado uno de {esp['tipo_final']}")

    for h in esp.get("herramientas", []):
        check(f"herramienta:{h}", h in nombres, f"llamadas={nombres}")

    if "cotizacion" in esp:
        llamadas = [h for h in herramientas if h["nombre"] == "calcular_cotizacion"]
        emitidas = [h for h in llamadas if (h.get("resultado") or {}).get("cotizacion_emitida")]
        candidatas = emitidas or llamadas
        args = {}
        if candidatas:
            try:
                args = json.loads(candidatas[-1]["argumentos"] or "{}")
            except json.JSONDecodeError:
                args = {}
        ok = bool(candidatas)
        detalle = f"args={args}"
        for clave, campo in (("valor", "valor_producto_usd"), ("peso", "peso_kg")):
            if clave in esp["cotizacion"]:
                try:
                    ok = ok and abs(float(args.get(campo)) - float(esp["cotizacion"][clave])) <= 0.011
                except (TypeError, ValueError):
                    ok = False
        check("argumentos_cotizacion", ok, f"{detalle}, esperado={esp['cotizacion']}")

    if "cotiza" in esp:
        cotizo = any("cotizacion" in (t.get("tipo_respuesta") or "").split("+") for t in procesados)
        check("cotiza" if esp["cotiza"] else "no_cotiza_indebidamente", cotizo == esp["cotiza"],
              f"cotizó={cotizo}")

    if "deriva" in esp:
        derivo = corrida.get("bot_activo_final") == 0
        check("deriva" if esp["deriva"] else "no_deriva", derivo == esp["deriva"], f"derivó={derivo}")

    bajo = textos_bot.lower()
    for t in esp.get("contiene", []):
        check(f"contiene:{t}", t.lower() in bajo)
    for t in esp.get("no_contiene", []):
        check(f"no_contiene:{t}", t.lower() not in bajo)
    return checks


# ---------------------------------------------------------------- KPIs

def _bloqueado_por_guardrail(r: Dict) -> bool:
    """La corrida fue bloqueada por el guardrail (respuesta guardrail o texto de bloqueo)."""
    if any(t.get("tipo_respuesta") == "guardrail" for t in r.get("turnos", [])):
        return True
    return any(c["check"].startswith("no_contiene:") and not c["ok"] for c in r.get("checks", []))


def calcular_kpis(casos: List[Dict], resultados: Dict[str, List[Dict]]) -> Dict:
    """KPIs del plan de evaluación a partir de las corridas verificadas."""
    por_id = {c["id"]: c for c in casos}
    corridas = [(por_id[cid], r) for cid, rs in resultados.items() for r in rs]

    def contar(filtro_caso, nombre_check=None, pred=None):
        ok = n = 0
        for caso, r in corridas:
            if not filtro_caso(caso):
                continue
            if nombre_check:
                cks = [c for c in r["checks"] if c["check"] == nombre_check or c["check"].startswith(nombre_check)]
                if not cks:
                    continue
                n += 1
                ok += all(c["ok"] for c in cks)
            else:
                n += 1
                ok += pred(r)
        return proporcion(ok, n)

    esp = lambda c: c.get("esperado", {})  # noqa: E731
    pass_k = {}
    for cid, rs in resultados.items():
        pass_k[cid] = all(r["exito"] for r in rs)
    k = max((len(rs) for rs in resultados.values()), default=0)

    return {
        "exito_tarea_pass1": contar(lambda c: True, pred=lambda r: r["exito"]),
        f"consistencia_pass^{k}": proporcion(sum(pass_k.values()), len(pass_k)),
        "K1_exactitud_herramienta": contar(lambda c: "tipo_final" in esp(c), "tipo_final"),
        "K2_exactitud_argumentos": contar(lambda c: "cotizacion" in esp(c), "argumentos_cotizacion"),
        "K3_sin_cotizacion_indebida": contar(lambda c: esp(c).get("cotiza") is False, "no_cotiza_indebidamente"),
        "K4_derivacion_recall": contar(lambda c: esp(c).get("deriva") is True, "deriva"),
        "K4_sin_derivacion_innecesaria": contar(lambda c: esp(c).get("deriva") is False, "no_deriva"),
        "K5_guardrail": contar(lambda c: c.get("categoria") == "guardrail", pred=lambda r: r["exito"]),
        # Falso positivo = el guardrail bloqueó un producto permitido (respuesta de tipo
        # guardrail o texto de bloqueo). Si el LLM no cotiza por otra razón, eso cuenta
        # en K1/K2 y pass^1, no aquí.
        "K5_sin_falsos_positivos": contar(lambda c: c.get("categoria") == "falso_amigo",
                                          pred=lambda r: not _bloqueado_por_guardrail(r)),
        "K11_adherencia_alcance": contar(lambda c: c.get("categoria") in ("alcance", "adversarial"),
                                          pred=lambda r: r["exito"]),
    }


# ---------------------------------------------------------------- Ejecución

class _ClienteConReintentos:
    """Envuelve el cliente de Groq: reintenta ante límites de uso (429) y errores transitorios."""

    def __init__(self, cliente, intentos: int = 6):
        self._cliente = cliente
        self._intentos = intentos
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        espera = 2.0
        for intento in range(self._intentos):
            try:
                return self._cliente.chat.completions.create(**kwargs)
            except Exception as e:  # RateLimitError, APIConnectionError, etc.
                nombre = type(e).__name__
                if intento == self._intentos - 1 or nombre not in (
                    "RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"
                ):
                    raise
                print(f"   ⏳ {nombre}: reintento en {espera:.0f} s")
                time.sleep(espera)
                if nombre == "RateLimitError":  # cuenta como espera por cuota, no como latencia
                    from llm_cliente import sumar_espera_ms
                    sumar_espera_ms(espera * 1000)
                espera = min(espera * 2, 60)


async def correr_caso(main, caso: Dict, repeticion: int, enviados: Dict[str, List[Dict]]) -> Dict:
    chat_id = f"EVAL-{caso['id']}-r{repeticion}-{uuid.uuid4().hex[:6]}"
    turnos = []
    for texto in caso["mensajes"]:
        main.registrar_mensaje_entrante(chat_id, NOMBRE_CLIENTE, texto)
        if not main.esta_bot_activo(chat_id):
            turnos.append({"cliente": texto, "silenciado": True, "respuestas": []})
            continue
        antes = len(enviados.get(chat_id, []))
        await main.procesar_mensaje_consolidado(chat_id, NOMBRE_CLIENTE, texto)
        respuestas = [_cuerpo(p) for p in enviados.get(chat_id, [])[antes:]]
        filas = [f for f in main.obtener_metricas() if f["chat_id"] == chat_id]
        m = filas[-1] if filas else {}
        turnos.append({
            "cliente": texto,
            "respuestas": [r for r in respuestas if r],
            "tipo_respuesta": m.get("tipo_respuesta"),
            "herramientas": json.loads(m.get("herramientas") or "[]"),
            "llamadas_llm": m.get("llamadas_llm"),
            "tokens_entrada": m.get("tokens_entrada"),
            "tokens_salida": m.get("tokens_salida"),
            "costo_usd": m.get("costo_usd"),
            "latencia_llm_ms": m.get("latencia_llm_ms"),
            "espera_limite_ms": m.get("espera_limite_ms") or 0.0,
            "latencia_procesamiento_ms": m.get("latencia_procesamiento_ms"),
        })
    chat = main.obtener_chat(chat_id) or {}
    return {"chat_id": chat_id, "repeticion": repeticion, "turnos": turnos,
            "bot_activo_final": chat.get("bot_activo")}


def _cuerpo(payload: Dict) -> Optional[str]:
    if payload.get("type") == "text":
        return payload["text"]["body"]
    if payload.get("type") == "proforma":  # contenido de la imagen, ver evaluar()
        return "[Proforma en imagen]\n" + payload["texto"]
    if payload.get("type") == "image":
        return payload["image"].get("caption")
    if payload.get("type") == "interactive":
        inter = payload["interactive"]
        cuerpo = inter["body"]["text"]
        if inter.get("type") == "button":
            cuerpo += "\n[Botones: " + " | ".join(b["reply"]["title"] for b in inter["action"]["buttons"]) + "]"
        elif inter.get("type") == "list":
            filas = inter["action"]["sections"][0]["rows"]
            cuerpo += "\n[Lista: " + " | ".join(f["title"] for f in filas) + "]"
        return cuerpo
    return None


async def evaluar(main, casos: List[Dict], repeticiones: int, pausa: float = 0.0) -> Dict[str, List[Dict]]:
    """Corre todos los casos. `main` es el módulo main ya importado en un entorno aislado."""
    enviados: Dict[str, List[Dict]] = {}

    async def post_falso(payload):
        destino = payload.get("to") or payload.get("recipient") or "_"
        enviados.setdefault(destino, []).append(payload)
        return True

    main._post_meta = post_falso  # nunca sale nada a Meta

    # La cotización llega como imagen: se registra su contenido en texto para los checks
    generar_imagen = main.generar_imagen_proforma

    def imagen_registrada(resultado, producto, nombre_cliente, chat_id, **kwargs):
        enviados.setdefault(chat_id, []).append(
            {"type": "proforma", "texto": main.GlobexPricingEngine.formatear_mensaje_whatsapp(resultado)})
        return generar_imagen(resultado, producto, nombre_cliente, chat_id, **kwargs)

    main.generar_imagen_proforma = imagen_registrada
    resultados: Dict[str, List[Dict]] = {}
    for i, caso in enumerate(casos, 1):
        resultados[caso["id"]] = []
        for rep in range(1, repeticiones + 1):
            corrida = await correr_caso(main, caso, rep, enviados)
            corrida["checks"] = evaluar_corrida(caso, corrida)
            corrida["exito"] = all(c["ok"] for c in corrida["checks"])
            resultados[caso["id"]].append(corrida)
            marca = "✅" if corrida["exito"] else "❌"
            print(f"[{i}/{len(casos)}] {caso['id']} r{rep} {marca}")
            if pausa:
                await asyncio.sleep(pausa)
    return resultados


# ---------------------------------------------------------------- Reporte

def _pct(p: Dict) -> str:
    if not p["n"]:
        return "—"
    li, ls = p["ic95"]
    return f"{p['valor'] * 100:.1f} % ({p['exitos']}/{p['n']}) · IC95 [{li * 100:.1f}, {ls * 100:.1f}]"


def _s(ms):
    return f"{ms / 1000:.2f} s" if ms is not None else "—"


def generar_reporte(meta: Dict, casos: List[Dict], resultados: Dict[str, List[Dict]], kpis: Dict,
                    resumen_costo: Dict) -> str:
    L = []
    L.append(f"# Reporte de evaluación de Globix · {meta['fecha']}\n")
    L.append(f"- **Casos:** `{meta['archivo_casos']}` ({len(casos)} casos × {meta['repeticiones']} repeticiones)")
    L.append(f"- **Modelo:** `{meta['modelo']}` · temperatura 0.2")
    L.append(f"- **Duración:** {meta['duracion_s']:.0f} s\n")

    L.append("## KPIs (IC 95 % de Clopper-Pearson)\n")
    L.append("| KPI | Resultado |\n| :-- | :-- |")
    for nombre, p in kpis.items():
        L.append(f"| {nombre} | {_pct(p)} |")

    L.append("\n## Costo y latencia\n")
    if resumen_costo.get("turnos"):
        lat = resumen_costo["latencia_procesamiento"]
        L.append("| Métrica | Valor |\n| :-- | :-- |")
        L.append(f"| Turnos / conversaciones | {resumen_costo['turnos']} / {resumen_costo['conversaciones']} |")
        L.append(f"| Llamadas al LLM por turno (promedio) | {resumen_costo['llamadas_llm_promedio']:.2f} |")
        L.append(f"| Tokens por turno (entrada + salida) | {resumen_costo['tokens_entrada_promedio']:.0f} + {resumen_costo['tokens_salida_promedio']:.0f} |")
        L.append(f"| Latencia del LLM por turno (p50 · p95) | {_s(resumen_costo['latencia_llm']['p50_ms'])} · {_s(resumen_costo['latencia_llm']['p95_ms'])} |")
        L.append(f"| Procesamiento por turno (p50 · p95) | {_s(lat['p50_ms'])} · {_s(lat['p95_ms'])} |")
        if lat["p50_ms"] is not None:
            L.append(f"| **Espera estimada del cliente** (+{DEBOUNCE_S:.0f} s de debounce, p50 · p95) | "
                     f"{_s(lat['p50_ms'] + DEBOUNCE_S * 1000)} · {_s(lat['p95_ms'] + DEBOUNCE_S * 1000)} |")
        sin = resumen_costo.get("latencia_total_sin_limites", {})
        lim = resumen_costo.get("espera_limite", {})
        if sin.get("p50_ms") is not None:
            L.append(f"| Espera del cliente **sin límites de cuota de Groq** (p50 · p95) | "
                     f"{_s(sin['p50_ms'] + DEBOUNCE_S * 1000)} · {_s(sin['p95_ms'] + DEBOUNCE_S * 1000)} |")
            L.append(f"| Turnos que esperaron por cuota (429) · espera total | "
                     f"{lim.get('turnos_afectados', 0)} · {_s(lim.get('total_ms', 0))} |")
        L.append(f"| Costo total de la evaluación | USD {resumen_costo['costo_total_usd']:.4f} |")
        L.append(f"| Costo por conversación | USD {resumen_costo['costo_por_conversacion_usd']:.5f} |")
        L.append(f"| Costo por 1 000 conversaciones | USD {resumen_costo['costo_por_1000_conversaciones_usd']:.2f} |")
        L.append("\nTipos de respuesta: " + ", ".join(f"`{k}` {v}" for k, v in resumen_costo["tipos_respuesta"].items()))

    L.append("\n## Resultado por caso\n")
    reps = meta["repeticiones"]
    L.append("| Caso | Categoría | " + " | ".join(f"r{i}" for i in range(1, reps + 1)) + " | Checks fallidos |")
    L.append("| :-- | :-- | " + " | ".join(":-:" for _ in range(reps)) + " | :-- |")
    for caso in casos:
        rs = resultados.get(caso["id"], [])
        fallidos = sorted({c["check"] for r in rs for c in r["checks"] if not c["ok"]})
        L.append(f"| {caso['id']} | {caso.get('categoria', '')} | "
                 + " | ".join("✅" if r["exito"] else "❌" for r in rs)
                 + f" | {', '.join(fallidos) or '—'} |")

    fallas = [(caso, r) for caso in casos for r in resultados.get(caso["id"], []) if not r["exito"]]
    L.append(f"\n## Detalle de fallas ({len(fallas)})\n")
    if not fallas:
        L.append("Sin fallas. 🎉")
    for caso, r in fallas:
        L.append(f"### {caso['id']} · r{r['repeticion']} — {caso.get('descripcion', '')}\n")
        L.append(f"`{r['chat_id']}` · esperado: `{json.dumps(caso.get('esperado', {}), ensure_ascii=False)}`\n")
        for c in r["checks"]:
            if not c["ok"]:
                L.append(f"- ❌ **{c['check']}** — {c['detalle']}")
        L.append("")
        for n, t in enumerate(r["turnos"], 1):
            L.append(f"**Turno {n}** · 👤 {t['cliente']}")
            if t.get("silenciado"):
                L.append("> _(bot silenciado: el mensaje queda para el asesor)_\n")
                continue
            L.append(f"- tipo: `{t.get('tipo_respuesta')}` · LLM x{t.get('llamadas_llm')} · "
                     f"{t.get('tokens_entrada')}+{t.get('tokens_salida')} tokens · "
                     f"LLM {_s(t.get('latencia_llm_ms'))} · total {_s(t.get('latencia_procesamiento_ms'))}"
                     + (f" · espera por cuota {_s(t.get('espera_limite_ms'))}" if t.get("espera_limite_ms") else ""))
            for h in t.get("herramientas", []):
                L.append(f"- 🔧 `{h['nombre']}({h.get('argumentos', '')})` → `{json.dumps(h.get('resultado'), ensure_ascii=False)}`")
            for resp in t.get("respuestas", []):
                L.append("> 🤖 " + resp.replace("\n", "\n> "))
            L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- CLI

def pdf_desde_json(ruta_json: str) -> str:
    """Genera el PDF de una corrida anterior a partir de su JSON de resultados."""
    with open(ruta_json, encoding="utf-8") as f:
        datos = json.load(f)
    meta = datos["meta"]
    with open(os.path.join(REPO, meta["archivo_casos"]), encoding="utf-8") as f:
        todos = json.load(f)["casos"]
    casos = [c for c in todos if c["id"] in datos["resultados"]]
    ruta_pdf = os.path.splitext(ruta_json)[0].replace("resultados_", "reporte_") + ".pdf"
    generar_reporte_pdf(meta, casos, datos["resultados"], datos["kpis"], datos["costo_latencia"], ruta_pdf, DEBOUNCE_S)
    print(f"Reporte PDF: {ruta_pdf}")
    return ruta_pdf


def main_cli(argv=None):
    parser = argparse.ArgumentParser(description="Evaluación de Globix con el LLM real.")
    parser.add_argument("--casos", default=os.path.join(REPO, "evaluacion", "casos_desarrollo.json"))
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--solo", default="", help="IDs separados por coma")
    parser.add_argument("--pausa", type=float, default=0.0, help="Segundos entre corridas (límites de Groq)")
    parser.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes"))
    parser.add_argument("--pdf-desde", default="",
                        help="Regenera el PDF desde un resultados_*.json ya guardado (no llama al LLM)")
    args = parser.parse_args(argv)

    if args.pdf_desde:
        return pdf_desde_json(args.pdf_desde)

    archivo_casos = os.path.abspath(args.casos)
    with open(archivo_casos, encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    if args.solo:
        ids = {x.strip() for x in args.solo.split(",") if x.strip()}
        casos = [c for c in casos if c["id"] in ids]
    salida = os.path.abspath(args.salida)
    os.makedirs(salida, exist_ok=True)

    # Entorno aislado: BD y PDFs en una carpeta temporal (nunca la globex.db real)
    sys.path.insert(0, REPO)
    os.chdir(tempfile.mkdtemp(prefix="globex_eval_"))
    import main  # noqa: E402  (carga el .env del repo: GROQ_API_KEY)
    from metricas import resumir  # noqa: E402

    if not os.getenv("GROQ_API_KEY"):
        sys.exit("Falta GROQ_API_KEY en el .env")
    main.client = _ClienteConReintentos(main.client)

    inicio = time.time()
    resultados = asyncio.run(evaluar(main, casos, args.repeticiones, args.pausa))
    duracion = time.time() - inicio

    kpis = calcular_kpis(casos, resultados)
    resumen_costo = resumir(main.obtener_metricas())
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    meta = {"fecha": datetime.now().strftime("%d/%m/%Y %H:%M"), "archivo_casos": os.path.relpath(archivo_casos, REPO),
            "repeticiones": args.repeticiones, "modelo": main.MODEL, "duracion_s": duracion}

    ruta_md = os.path.join(salida, f"reporte_{marca}.md")
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(generar_reporte(meta, casos, resultados, kpis, resumen_costo))
    ruta_json = os.path.join(salida, f"resultados_{marca}.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "kpis": kpis, "costo_latencia": resumen_costo, "resultados": resultados},
                  f, ensure_ascii=False, indent=2, default=str)

    ruta_pdf = os.path.join(salida, f"reporte_{marca}.pdf")
    generar_reporte_pdf(meta, casos, resultados, kpis, resumen_costo, ruta_pdf, DEBOUNCE_S)

    print(f"\nÉxito (pass^1): {_pct(kpis['exito_tarea_pass1'])}")
    print(f"Reporte PDF: {ruta_pdf}\nReporte MD:  {ruta_md}\nDatos:       {ruta_json}")
    return ruta_md


if __name__ == "__main__":
    main_cli()
