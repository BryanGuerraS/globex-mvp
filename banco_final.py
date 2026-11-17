"""Corrida del banco final desde un endpoint, con su informe generado en ese momento.

`POST /api/eval/banco-final` recibe el banco del equipo (zip de la carpeta Globex_Bancos_V2), verifica su
manifiesto SHA-256, corre todos los casos con el mismo flujo que /api/eval/caso (keys de Cerebras en el
orden configurado en Render), califica la calidad con el juez del equipo usando la key de PAGO y arma el
informe (Markdown + JSON). El banco no vive en el repositorio (no debe quedar público): llega en la llamada.

Este módulo tiene lo que no depende de FastAPI: preparar el banco, calcular los KPI y redactar el informe.
La orquestación (correr los casos) está en main.py porque reutiliza su flujo de evaluación.
"""

import hashlib
import io
import json
import statistics
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "evaluacion"))
from banco_final_a_json import convertir  # noqa: E402
from metricas import clopper_pearson  # noqa: E402

MAX_ZIP_BYTES = 20 * 1024 * 1024


class BancoInvalido(ValueError):
    pass


def preparar(zip_bytes: bytes) -> Tuple[Path, Dict, str]:
    """Descomprime el banco en una carpeta temporal, verifica el manifiesto y lo convierte.

    Devuelve (carpeta del banco, JSON de ejecución, SHA-256 del manifiesto). Lanza BancoInvalido si el
    zip no es válido, falta el índice o algún archivo no coincide con el manifiesto.
    """
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise BancoInvalido("El zip supera los 20 MB")
    try:
        archivo = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise BancoInvalido("El cuerpo no es un zip válido") from e
    destino = Path(tempfile.mkdtemp(prefix="banco_final_"))
    for nombre in archivo.namelist():
        ruta = (destino / nombre).resolve()
        if not str(ruta).startswith(str(destino.resolve())):  # sin rutas que salgan de la carpeta
            raise BancoInvalido(f"Ruta no permitida en el zip: {nombre}")
    archivo.extractall(destino)
    indices = list(destino.rglob("00_Indice_Bancos.txt"))
    if len(indices) != 1:
        raise BancoInvalido("El zip debe traer una sola carpeta con 00_Indice_Bancos.txt")
    carpeta = indices[0].parent
    banco, sha = verificar_carpeta(carpeta)
    return carpeta, banco, sha


def verificar_carpeta(carpeta: Path) -> Tuple[Dict, str]:
    """Verifica cada archivo de la carpeta del banco contra MANIFIESTO_SHA256.txt y la convierte.
    Devuelve (JSON de ejecución, SHA-256 del manifiesto). Lanza BancoInvalido si algo no coincide."""
    carpeta = Path(carpeta)
    if not (carpeta / "00_Indice_Bancos.txt").exists():
        raise BancoInvalido("La carpeta no tiene 00_Indice_Bancos.txt")
    manifiesto = carpeta / "MANIFIESTO_SHA256.txt"
    if not manifiesto.exists():
        raise BancoInvalido("Falta MANIFIESTO_SHA256.txt")
    distintos = []
    for linea in manifiesto.read_text(encoding="utf-8").splitlines():
        partes = linea.strip().split(None, 1)
        if len(partes) != 2:
            continue
        esperado, relativo = partes
        ruta = carpeta / relativo.strip().lstrip("*")
        if not ruta.exists() or hashlib.sha256(ruta.read_bytes()).hexdigest() != esperado.lower():
            distintos.append(relativo.strip())
    if distintos:
        raise BancoInvalido(f"Archivos que no coinciden con el manifiesto: {distintos[:10]}")
    sha = hashlib.sha256(manifiesto.read_bytes()).hexdigest()
    try:
        banco = convertir(carpeta)
    except SystemExit as e:  # convertir() valida los ids contra el índice
        raise BancoInvalido(str(e)) from e
    return banco, sha


def _pct(n: int, d: int) -> Optional[float]:
    return round(100 * n / d, 2) if d else None


def _ic(n: int, d: int) -> Optional[List[float]]:
    return [round(100 * x, 1) for x in clopper_pearson(n, d)] if d else None


# Metas del proyecto para cada indicador (en %)
METAS = {"faq": 85, "derivacion": 80, "productos": 85, "cotizaciones": 95, "recopilacion": 90, "resumen": 85}


def calcular_kpis(filas: List[Dict], revision: Dict, juez: Dict, indice: Optional[Dict] = None) -> List[Dict]:
    """Los 6 indicadores del proyecto con su meta (`METAS`). `indice` se acepta por compatibilidad."""
    faq, pro = juez.get("FAQ", {}), juez.get("PRODUCTOS", {})
    cot, der = revision["cotizaciones"], revision["derivacion_efectiva"]
    bloq = revision["productos_bloqueados"]
    res, rec = juez.get("RESUMEN", {}), juez.get("RECOPILACION", {})

    def fila(nombre, n, d, meta, porcentaje=None, extra=None):
        p = porcentaje if porcentaje is not None else _pct(n, d)
        return {"indicador": nombre, "aciertos": n, "casos": d, "porcentaje": p,
                "ic95": _ic(n, d) if n is not None and d else None, "meta": meta,
                "cumple": p is not None and p >= meta, **(extra or {})}

    return [
        fila("Calidad de respuesta a preguntas frecuentes", faq.get("aceptables"), faq.get("decididos"),
             METAS["faq"], extra={"fallas": faq.get("no_aceptables", [])}),
        fila("Derivación correcta", der["derivadas"], der["n"], METAS["derivacion"],
             extra={"fallas": [x["id"] for x in der["fallas"]]}),
        fila("Calidad de respuesta sobre productos con condiciones especiales", pro.get("aceptables"),
             pro.get("decididos"), METAS["productos"],
             extra={"fallas": pro.get("no_aceptables", []), "avances_indebidos": pro.get("avances_indebidos", []),
                    "cotizaciones_emitidas_a_bloqueados": bloq["avances_indebidos"]}),
        fila("Exactitud del total cotizado", cot["correctas"], cot["n"], METAS["cotizaciones"],
             extra={"fallas": [x["id"] for x in cot["fallas"]]}),
        fila("Exactitud y completitud de los datos recopilados", None, rec.get("evaluados"),
             METAS["recopilacion"], porcentaje=rec.get("promedio_porcentaje")),
        fila("Calidad del resumen para el asesor", res.get("aceptables"), res.get("decididos"),
             METAS["resumen"], extra={"fallas": res.get("no_aceptables", [])}),
    ]


def combinar_kpis(corridas: List[List[Dict]]) -> List[Dict]:
    """Promedio y rango de cada indicador sobre varias corridas; cumple si el promedio alcanza la meta."""
    combinados = []
    for i, base in enumerate(corridas[0]):
        valores = [c[i]["porcentaje"] for c in corridas if c[i].get("porcentaje") is not None]
        prom = round(sum(valores) / len(valores), 1) if valores else None
        combinados.append({
            "indicador": base["indicador"], "meta": base["meta"], "porcentaje": prom,
            "minimo": min(valores) if valores else None, "maximo": max(valores) if valores else None,
            "por_corrida": [c[i].get("porcentaje") for c in corridas],
            "aciertos_por_corrida": [c[i].get("aciertos") for c in corridas],
            "casos": base.get("casos"), "corridas": len(corridas),
            "corridas_que_cumplen": sum(1 for c in corridas if c[i]["cumple"]),
            "cumple": prom is not None and prom >= base["meta"],
        })
    return combinados


def tiempos(filas: List[Dict]) -> Dict:
    proc = [t["latencia_procesamiento_ms"] for f in filas for t in f.get("registros_tiempo", [])
            if t.get("latencia_procesamiento_ms") is not None]
    if not proc:
        return {}
    proc.sort()
    return {"turnos": len(proc), "p50_s": round(statistics.median(proc) / 1000, 2),
            "p95_s": round(proc[min(len(proc) - 1, int(0.95 * len(proc)))] / 1000, 2)}


def informe_markdown(meta: Dict, kpis: List[Dict], t: Dict) -> str:
    def num(x):
        return "—" if x is None else f"{x:.2f} %"
    lineas = [
        "# Informe del banco final — Globix", "",
        f"- **Generado:** {meta['generado']} (hora de Lima)",
        f"- **Versión del chatbot:** commit `{meta.get('commit') or 'desconocido'}` · {meta['modelo_chatbot']}",
        f"- **Banco:** {meta['version_banco']} · SHA-256 del manifiesto `{meta['sha_manifiesto'][:16]}…` (verificado)",
        f"- **Juez:** {meta['modelo_juez']} con la key de pago · prompts del banco (`01_System_Prompts`)",
        f"- **Casos:** {meta['ejecutados']}/{meta['total']} ejecutados · errores de ejecución: {meta['errores']}",
        f"- **Duración:** {meta['duracion_min']} min", "",
        "| Indicador | Resultado | IC 95 % | Meta | Cumple |", "| --- | --- | --- | --- | --- |",
    ]
    for k in kpis:
        detalle = f"{k['aciertos']}/{k['casos']} = " if k.get("aciertos") is not None else (
            f"promedio de {k['casos']} chats: " if k.get("casos") else "")
        ic = f"{k['ic95'][0]}–{k['ic95'][1]} %" if k.get("ic95") else "—"
        lineas.append(f"| {k['indicador']} | {detalle}{num(k['porcentaje'])} | {ic} | {k['meta']} % | "
                      f"{'Sí' if k['cumple'] else 'No'} |")
    lineas += ["", "## Detalle", ""]
    for k in kpis:
        partes = []
        if k.get("fallas"):
            partes.append(f"no aprobados: {', '.join(k['fallas'])}")
        if k.get("avances_indebidos"):
            partes.append(f"avances indebidos a cotización (juez): {', '.join(k['avances_indebidos'])}")
        if "cotizaciones_emitidas_a_bloqueados" in k:
            emitidas = k["cotizaciones_emitidas_a_bloqueados"]
            partes.append(f"cotizaciones emitidas a pedidos bloqueados: {len(emitidas)}"
                          + (f" ({', '.join(x['id'] for x in emitidas)})" if emitidas else ""))
        lineas.append(f"- **{k['indicador']}:** {'; '.join(partes) if partes else 'sin fallas'}")
    if t:
        lineas += ["", f"**Tiempo de procesamiento por turno:** p50 {t['p50_s']} s · p95 {t['p95_s']} s "
                       f"({t['turnos']} turnos; no incluye los 5 s de agrupación de WhatsApp)."]
    lineas += ["", "## Cómo leer este informe", "",
               "- Derivación, cotizaciones y cotizaciones emitidas a bloqueados se miden con los registros del sistema "
               "contra la ficha de cada caso; FAQ, productos, recopilación y resumen los califica el juez (LLM) con la "
               "rúbrica del banco. El juez puede variar unos puntos entre corridas.",
               "- IC 95 % de Clopper-Pearson. La recopilación es el promedio por chat (fórmula del prompt del juez).",
               "- Un indicador cumple si alcanza su meta."]
    return "\n".join(lineas) + "\n"
