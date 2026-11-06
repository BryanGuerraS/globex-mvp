"""LLM como juez: aplica la rúbrica de docs/rubrica_calidad.md a conversaciones de Globix.

Usa un modelo de otra familia que el de Globix (por defecto qwen/qwen3.8-27b;
Globix usa openai/gpt-oss-120b) para reducir el sesgo de autopreferencia.
Escribe una hoja con el mismo formato que la de un revisor humano, así se
compara con `revision_humana.py kappa`.

Uso (desde la raíz del repo):
    # Juzgar una muestra de una corrida de evaluar.py (exporta la muestra y la juzga)
    python evaluacion/juez_llm.py --resultados evaluacion/reportes/resultados_X.json --muestra 60

    # Juzgar exactamente las conversaciones de una hoja ya exportada
    python evaluacion/juez_llm.py --hoja evaluacion/reportes/revision_humana/hoja_revisor_A.csv

    # Dos pasadas para medir la estabilidad del juez (kappa juez vs. juez)
    python evaluacion/juez_llm.py --resultados ... --pasadas 2

Key: GROQ_API_KEY_JUEZ (si se agota, sigue con GROQ_API_KEY y las de respaldo).
El juez no reemplaza a la revisión humana: su resultado se reporta solo si su
kappa contra un revisor humano es >= 0.6 (ver la rúbrica).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from evaluacion import revision_humana as rh  # noqa: E402

MODELO_JUEZ = os.getenv("GROQ_MODELO_JUEZ", "qwen/qwen3.8-27b")
RUBRICA = os.path.join(REPO, "docs", "rubrica_calidad.md")
INTENTOS = 3


def texto_rubrica(ruta: str = RUBRICA) -> str:
    """Las secciones de la rúbrica que necesita el juez: valores, criterios y resultado."""
    with open(ruta, encoding="utf-8") as f:
        texto = f.read()
    inicio = texto.index("## Qué se revisa")
    fin = texto.index("## Procedimiento")
    return texto[inicio:fin].strip()


def informacion_aprobada() -> str:
    import knowledge_base

    faq = "\n".join(f"- {tema}: {v['contenido']}" for tema, v in knowledge_base.KB_GLOBEX.items())
    return (
        "Reglas de cotización aprobadas por Globex: USD 9 por kg (mínimo 1 kg facturable), USD 9 de trámite "
        "aduanero, tributos aproximados de 22.72 % sobre el valor CIF (producto + flete + trámite) solo si el "
        "PRODUCTO vale más de USD 200, cotización automática solo si el PRODUCTO vale hasta USD 1 200 (el total "
        "con flete y tributos sí puede superar USD 1 200; si el producto vale más, se deriva al asesor), "
        "vigencia 24 horas.\n"
        "Los montos de la proforma los calcula un motor de reglas ya verificado: NO recalcules los montos; "
        "revisa solo que el producto, el precio y el peso usados sean los que dijo el cliente.\n"
        "'[Proforma en imagen]' indica que la cotización se envió como imagen; su contenido va debajo.\n"
        "'[Botones: ...]' son los botones de WhatsApp que acompañan al mensaje.\n"
        f"Preguntas frecuentes aprobadas (knowledge_base.py):\n{faq}"
    )


def prompt_sistema() -> str:
    esquema = ", ".join(f'"{c}": {{"motivo": "...", "valor": "S|N{"|NA" if c in rh.SOLO_CON_NA else ""}"}}'
                        for c in rh.CRITERIOS)
    return (
        "Eres un revisor de calidad de Globex, un courier de compras de EE. UU. a Perú. Evalúas conversaciones "
        "de WhatsApp entre un cliente y Globix, el asistente virtual de primera atención, con la rúbrica de abajo. "
        "Evalúas solo lo que hizo Globix. Sé estricto y concreto: si un criterio falla, di exactamente qué "
        "mensaje falla y por qué.\n\n"
        f"# Rúbrica\n{texto_rubrica()}\n\n# Información aprobada por Globex\n{informacion_aprobada()}\n\n"
        "# Formato de salida\nResponde SOLO un objeto JSON con esta forma (primero el motivo, luego el valor):\n"
        f"{{{esquema}}}\n"
        "Valores: S, N o NA. NA solo en C5_derivacion. El motivo, en español y en una o dos frases."
    )


def _extraer_json(texto: str) -> Dict:
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin < 0:
        raise ValueError("La respuesta no contiene JSON")
    return json.loads(texto[inicio:fin + 1])


def validar_veredicto(datos: Dict) -> Dict[str, Dict[str, str]]:
    """Normaliza y valida la salida del juez: todos los criterios, valores válidos, NA solo en C5."""
    # El modelo a veces escribe la clave con tildes ("C5_derivación"): se reconoce por el prefijo C1…C6
    por_prefijo = {str(k).strip().upper()[:2]: v for k, v in datos.items()}
    veredicto = {}
    for c in rh.CRITERIOS:
        item = datos.get(c, por_prefijo.get(c[:2]))
        if not isinstance(item, dict):
            raise ValueError(f"Falta el criterio {c}")
        valor = rh.normalizar(item.get("valor"))
        if valor is None:
            raise ValueError(f"{c} sin valor")
        if valor == "NA" and c not in rh.SOLO_CON_NA:
            raise ValueError(f"{c}: NA no permitido")
        veredicto[c] = {"valor": valor, "motivo": str(item.get("motivo", "")).strip()}
    return veredicto


def juzgar(conversacion: str, llamar: Callable[[List[Dict]], str], sistema: Optional[str] = None) -> Dict:
    """Pide el veredicto al juez; reintenta si la salida no cumple el formato."""
    mensajes = [
        {"role": "system", "content": sistema or prompt_sistema()},
        {"role": "user", "content": f"Conversación a evaluar:\n\n{conversacion}"},
    ]
    error = None
    for _ in range(INTENTOS):
        try:
            return validar_veredicto(_extraer_json(llamar(mensajes)))
        except (ValueError, json.JSONDecodeError) as e:
            error = e
    raise ValueError(f"El juez no devolvió un veredicto válido tras {INTENTOS} intentos: {error}")


def llamador_groq(modelo: str = MODELO_JUEZ) -> Callable[[List[Dict]], str]:
    from dotenv import load_dotenv

    from llm_cliente import crear_cliente, keys_de_respaldo

    load_dotenv(os.path.join(REPO, ".env"))
    principal = os.getenv("GROQ_API_KEY_JUEZ") or os.getenv("GROQ_API_KEY")
    respaldos = [k for k in [os.getenv("GROQ_API_KEY"), *keys_de_respaldo(os.environ)] if k and k != principal]
    cliente = crear_cliente(principal, respaldos)
    uso = {"entrada": 0, "salida": 0, "llamadas": 0}

    def llamar(mensajes):
        r = cliente.chat.completions.create(model=modelo, messages=mensajes, temperature=0,
                                            response_format={"type": "json_object"})
        uso["entrada"] += r.usage.prompt_tokens
        uso["salida"] += r.usage.completion_tokens
        uso["llamadas"] += 1
        return r.choices[0].message.content

    llamar.uso = uso
    return llamar


def juzgar_hoja(ruta_hoja: str, ruta_salida: str, llamar: Callable, avisar=print) -> Dict[str, Dict]:
    """Juzga cada conversación de una hoja y escribe la hoja del juez (mismos ids)."""
    filas = rh.leer_csv(ruta_hoja)
    sistema = prompt_sistema()
    salida, motivos = [], {}
    for i, fila in enumerate(filas, 1):
        try:
            veredicto = juzgar(fila["conversacion"], llamar, sistema)
        except ValueError as e:  # se deja vacía (no cuenta) y se sigue con las demás
            avisar(f"  {i}/{len(filas)} {fila['id']}: sin veredicto ({e})")
            salida.append({"id": fila["id"], "conversacion": fila["conversacion"], "comentario": f"sin veredicto: {e}"})
            continue
        fallas = [f"{c}: {v['motivo']}" for c, v in veredicto.items() if v["valor"] == "N"]
        salida.append({"id": fila["id"], "conversacion": fila["conversacion"],
                       **{c: v["valor"] for c, v in veredicto.items()},
                       "comentario": " | ".join(fallas)})
        motivos[fila["id"]] = veredicto
        avisar(f"  {i}/{len(filas)} {fila['id']}: " + " ".join(f"{c[:2]}={v['valor']}" for c, v in veredicto.items()))
    rh.escribir_csv(ruta_salida, rh.COLUMNAS_HOJA, salida)
    with open(ruta_salida.replace(".csv", "_motivos.json"), "w", encoding="utf-8") as f:
        json.dump(motivos, f, ensure_ascii=False, indent=1)
    return motivos


def comparar_con_checks(hoja_juez: str, clave_csv: str) -> Optional[Dict]:
    """Coincidencia entre la 'atención correcta' del juez y los checks automáticos de evaluar.py."""
    clave = rh.leer_csv(clave_csv)
    if not clave or not clave[0].get("archivo"):
        return None
    ruta = os.path.join(os.path.dirname(clave_csv), clave[0]["archivo"])
    if not os.path.exists(ruta):
        ruta = os.path.join(REPO, "evaluacion", "reportes", clave[0]["archivo"])
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as f:
        resultados = json.load(f)["resultados"]
    juez = rh.leer_hoja(hoja_juez)
    pares = []
    for fila in clave:
        corrida = resultados.get(fila["caso"], [{}])[0]
        if fila["id"] in juez and "exito" in corrida:
            pares.append((fila["id"], fila["caso"], "S" if corrida["exito"] else "N",
                          rh.atencion_correcta(juez[fila["id"]])))
    distintos = [p for p in pares if p[2] != p[3]]
    return {"n": len(pares), "coinciden": len(pares) - len(distintos), "distintos": distintos}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    origen = parser.add_mutually_exclusive_group(required=True)
    origen.add_argument("--resultados", help="JSON de evaluar.py: se exporta una muestra y se juzga")
    origen.add_argument("--hoja", help="Hoja ya exportada por revision_humana.py")
    parser.add_argument("--muestra", type=int, default=60)
    parser.add_argument("--semilla", type=int, default=7)
    parser.add_argument("--pasadas", type=int, default=1, help="2 = medir la estabilidad del juez")
    parser.add_argument("--modelo", default=MODELO_JUEZ)
    parser.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes", "revision_humana"))
    args = parser.parse_args(argv)

    os.makedirs(args.salida, exist_ok=True)
    if args.resultados:
        rutas = rh.exportar(args.resultados, args.muestra, args.salida, args.semilla)
        hoja, clave = rutas["A"], rutas["clave"]
    else:
        hoja = args.hoja
        clave = os.path.join(os.path.dirname(hoja), "clave.csv")

    llamar = llamador_groq(args.modelo)
    inicio = time.time()
    hojas_juez = []
    for p in range(1, args.pasadas + 1):
        ruta = os.path.join(args.salida, f"hoja_juez{'' if p == 1 else f'_{p}'}.csv")
        print(f"Pasada {p} con {args.modelo}…")
        juzgar_hoja(hoja, ruta, llamar)
        hojas_juez.append(ruta)

    lineas = [f"# LLM como juez · {datetime.now():%d/%m/%Y %H:%M}", "",
              f"Modelo juez: `{args.modelo}` (Globix usa openai/gpt-oss-120b). Hoja: `{os.path.basename(hoja)}`.",
              f"Llamadas: {llamar.uso['llamadas']} · tokens {llamar.uso['entrada']} + {llamar.uso['salida']} · "
              f"{time.time() - inicio:.0f} s.", ""]
    final = rh.resultado_final(rh.leer_hoja(hojas_juez[0]),
                               {f["id"]: f for f in rh.leer_csv(clave)} if os.path.exists(clave) else None)
    lineas += ["## Resultado según el juez", "", *rh.tabla_resultado(final)]
    if len(hojas_juez) > 1:
        estabilidad = rh.medir_acuerdo(rh.leer_hoja(hojas_juez[0]), rh.leer_hoja(hojas_juez[1]))
        lineas += ["", "## Estabilidad del juez (pasada 1 vs. pasada 2)", "", *rh.tabla_acuerdo(estabilidad)]
    checks = comparar_con_checks(hojas_juez[0], clave) if os.path.exists(clave) else None
    if checks:
        lineas += ["", "## Juez vs. checks automáticos de evaluar.py", "",
                   f"Coinciden en {checks['coinciden']} de {checks['n']} conversaciones."]
        if checks["distintos"]:
            lineas += ["", "| id | caso | checks | juez |", "| --- | --- | --- | --- |"]
            lineas += [f"| {i} | {c} | {a} | {b} |" for i, c, a, b in checks["distintos"]]
    texto = "\n".join(lineas) + "\n"
    ruta_md = os.path.join(args.salida, f"reporte_juez_{datetime.now():%Y%m%d_%H%M}.md")
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Reporte: {ruta_md}")


if __name__ == "__main__":
    main()
