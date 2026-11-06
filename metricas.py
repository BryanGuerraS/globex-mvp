"""Medición de costo y latencia por turno del bot.

Un "turno" es cada vez que Globix procesa los mensajes consolidados de un
cliente y responde. Se registra:
- llamadas al LLM, tokens de entrada/salida y costo estimado en USD;
- latencia del LLM, del procesamiento completo y la total que percibe el
  cliente (desde que llega su primer mensaje, incluye la espera de 5 s del
  debounce);
- herramientas que llamó el LLM, con sus argumentos y resultado.

Las funciones de resumen son puras para reutilizarlas en el script de evaluación.
"""

import json
import math
import os
import statistics
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

# Precio de Groq para openai/gpt-oss-120b (USD por millón de tokens).
# Fuente: groq.com/pricing (oct. 2026). Configurable si cambia.
PRECIO_ENTRADA_USD_M = float(os.getenv("GROQ_PRECIO_ENTRADA_USD_M", "0.15"))
PRECIO_SALIDA_USD_M = float(os.getenv("GROQ_PRECIO_SALIDA_USD_M", "0.60"))


def costo_usd(tokens_entrada: int, tokens_salida: int) -> float:
    return (tokens_entrada * PRECIO_ENTRADA_USD_M + tokens_salida * PRECIO_SALIDA_USD_M) / 1_000_000


class MedidorTurno:
    """Acumula lo que pasa en un turno y arma la fila para la BD."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.llamadas_llm = 0
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.latencia_llm_ms = 0.0
        self.espera_limite_ms = 0.0
        self.herramientas: List[Dict] = []
        self.tipo_respuesta = "libre"

    def registrar_llamada_llm(self, respuesta, ms: float, espera_limite_ms: float = 0.0):
        """ms: tiempo total de la llamada; espera_limite_ms: parte perdida por límites de
        Groq (429 y esperas). latencia_llm_ms guarda solo el tiempo real del LLM."""
        self.llamadas_llm += 1
        espera = min(max(espera_limite_ms, 0.0), ms)
        self.espera_limite_ms += espera
        self.latencia_llm_ms += ms - espera
        uso = getattr(respuesta, "usage", None)
        if uso is not None:
            self.tokens_entrada += int(getattr(uso, "prompt_tokens", 0) or 0)
            self.tokens_salida += int(getattr(uso, "completion_tokens", 0) or 0)

    def registrar_herramienta(self, nombre: str, argumentos: str, resultado: Dict):
        self.herramientas.append(
            {"nombre": nombre, "argumentos": (argumentos or "")[:500], "resultado": resultado}
        )

    def fila(self, latencia_procesamiento_ms: float, latencia_total_ms: float) -> Dict:
        return {
            "chat_id": self.chat_id,
            "tipo_respuesta": self.tipo_respuesta,
            "llamadas_llm": self.llamadas_llm,
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "costo_usd": costo_usd(self.tokens_entrada, self.tokens_salida),
            "latencia_llm_ms": round(self.latencia_llm_ms, 1),
            "espera_limite_ms": round(self.espera_limite_ms, 1),
            "latencia_procesamiento_ms": round(latencia_procesamiento_ms, 1),
            "latencia_total_ms": round(latencia_total_ms, 1),
            "herramientas": json.dumps(self.herramientas, ensure_ascii=False, default=str),
        }


def _percentil(valores: List[float], p: float) -> Optional[float]:
    """Percentil por interpolación lineal (p entre 0 y 100)."""
    if not valores:
        return None
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    k = (len(ordenados) - 1) * p / 100
    piso = int(k)
    techo = min(piso + 1, len(ordenados) - 1)
    return ordenados[piso] + (ordenados[techo] - ordenados[piso]) * (k - piso)


def _resumen_latencia(valores: List[float]) -> Dict:
    return {
        "p50_ms": _percentil(valores, 50),
        "p95_ms": _percentil(valores, 95),
        "max_ms": max(valores) if valores else None,
    }


def resumir(filas: Iterable[Dict]) -> Dict:
    """Resumen de costo y latencia a partir de las filas de metricas_turno."""
    filas = list(filas)
    if not filas:
        return {"turnos": 0}
    chats = {f["chat_id"] for f in filas}
    costo_total = sum(f["costo_usd"] or 0 for f in filas)
    con_llm = [f for f in filas if (f["llamadas_llm"] or 0) > 0]
    tipos: Dict[str, int] = {}
    for f in filas:
        tipos[f["tipo_respuesta"]] = tipos.get(f["tipo_respuesta"], 0) + 1
    return {
        "turnos": len(filas),
        "conversaciones": len(chats),
        "llamadas_llm_promedio": statistics.mean(f["llamadas_llm"] or 0 for f in filas),
        "tokens_entrada_promedio": statistics.mean(f["tokens_entrada"] or 0 for f in filas),
        "tokens_salida_promedio": statistics.mean(f["tokens_salida"] or 0 for f in filas),
        "costo_total_usd": costo_total,
        "costo_por_turno_usd": costo_total / len(filas),
        "costo_por_conversacion_usd": costo_total / len(chats),
        "costo_por_1000_conversaciones_usd": 1000 * costo_total / len(chats),
        "latencia_llm": _resumen_latencia([f["latencia_llm_ms"] for f in con_llm]),
        "latencia_procesamiento": _resumen_latencia([f["latencia_procesamiento_ms"] for f in filas]),
        "latencia_total_cliente": _resumen_latencia([f["latencia_total_ms"] for f in filas]),
        # Lo mismo descontando la espera por límites de Groq (cuota del plan, no velocidad)
        "latencia_total_sin_limites": _resumen_latencia(
            [f["latencia_total_ms"] - (f.get("espera_limite_ms") or 0) for f in filas]
        ),
        "espera_limite": {
            "turnos_afectados": sum(1 for f in filas if (f.get("espera_limite_ms") or 0) > 0),
            "total_ms": sum(f.get("espera_limite_ms") or 0 for f in filas),
            **_resumen_latencia([f["espera_limite_ms"] for f in filas if (f.get("espera_limite_ms") or 0) > 0]),
        },
        "tipos_respuesta": tipos,
        "precio_usd_por_millon": {"entrada": PRECIO_ENTRADA_USD_M, "salida": PRECIO_SALIDA_USD_M},
    }


# ---------------------------------------------------------------- Estadística

def _binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(exitos: int, n: int, confianza: float = 0.95) -> Tuple[float, float]:
    """IC exacto de Clopper-Pearson para una proporción (por bisección)."""
    if n == 0:
        return (0.0, 1.0)
    alfa = 1 - confianza
    inferior = 0.0
    if exitos > 0:
        lo, hi = 0.0, 1.0
        for _ in range(100):  # P(X >= exitos | p) = alfa/2
            mid = (lo + hi) / 2
            if 1 - _binom_cdf(exitos - 1, n, mid) < alfa / 2:
                lo = mid
            else:
                hi = mid
        inferior = (lo + hi) / 2
    superior = 1.0
    if exitos < n:
        lo, hi = 0.0, 1.0
        for _ in range(100):  # P(X <= exitos | p) = alfa/2
            mid = (lo + hi) / 2
            if _binom_cdf(exitos, n, mid) > alfa / 2:
                lo = mid
            else:
                hi = mid
        superior = (lo + hi) / 2
    return (inferior, superior)


# ------------------------------------------- KPI: primera atención útil <= 60 min

# Plazo del KPI de impacto (minutos). Un saludo automático no cuenta como atención útil:
# qué respuestas cuentan lo define TIPOS_ATENCION_UTIL en main.py.
PLAZO_ATENCION_MIN = 60


def _fecha(valor) -> Optional[datetime]:
    if valor is None or isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def kpi_primera_atencion(
    chats: Iterable[Dict], momento: datetime, desde: Optional[datetime] = None,
    plazo_min: int = PLAZO_ATENCION_MIN, campo: str = "primera_util",
) -> Dict:
    """% de leads con primera atención útil en <= plazo_min, con IC 95 % (Clopper-Pearson).

    Lead = chat con primer mensaje registrado (desde `desde`, si se indica).
    Se evalúan los leads cuya ventana ya cerró o que ya recibieron atención útil;
    los que aún están dentro del plazo sin atención quedan como "en curso".
    campo: "primera_util" (definición del E3) o "primera_resolutiva" (estricta:
    solo cotización, FAQ, aviso de restricción o mensaje del asesor).
    """
    evaluables, a_tiempo, en_curso, sin_atencion = 0, 0, 0, 0
    minutos: List[float] = []
    por_actor: Dict[str, Dict[str, int]] = {}
    for chat in chats:
        inicio = _fecha(chat.get("primer_mensaje_at"))
        if inicio is None or (desde is not None and inicio < desde):
            continue
        util = _fecha(chat.get(f"{campo}_at"))
        if util is None:
            if (momento - inicio).total_seconds() / 60 <= plazo_min:
                en_curso += 1
                continue
            evaluables += 1
            sin_atencion += 1
            continue
        evaluables += 1
        espera = max(0.0, (util - inicio).total_seconds() / 60)
        minutos.append(espera)
        actor = chat.get(f"{campo}_actor") or "bot"
        cuenta = por_actor.setdefault(actor, {"atendidos": 0, "a_tiempo": 0})
        cuenta["atendidos"] += 1
        if espera <= plazo_min:
            a_tiempo += 1
            cuenta["a_tiempo"] += 1
    li, ls = clopper_pearson(a_tiempo, evaluables)
    return {
        "plazo_min": plazo_min,
        "leads_evaluables": evaluables,
        "a_tiempo": a_tiempo,
        "porcentaje": a_tiempo / evaluables if evaluables else None,
        "ic95": [li, ls] if evaluables else None,
        "sin_atencion_util": sin_atencion,
        "en_curso": en_curso,
        "minutos_p50": _percentil(minutos, 50),
        "minutos_p95": _percentil(minutos, 95),
        "por_actor": por_actor,
    }


# ------------------------------------- Revisión del asesor (componente 5 del E3)

# Tipos de revisión que registra la consola.
REVISION_VALIDADA = "cotizacion_validada"    # el asesor envió el PDF formal sin cambios
REVISION_CORREGIDA = "cotizacion_corregida"  # la cotización de Globix tenía un error
REVISION_ERROR = "error_reportado"           # error en cualquier otro mensaje de Globix
TIPOS_REVISION = (REVISION_VALIDADA, REVISION_CORREGIDA, REVISION_ERROR)

# Qué estuvo mal (lista corta para que el asesor no tenga que escribir).
CATEGORIAS_ERROR = {
    "dato_mal_extraido": "Dato mal extraído (producto, precio o peso)",
    "no_debio_cotizar": "No debió cotizar",
    "debio_derivar": "Debió derivar al asesor",
    "no_debio_derivar": "No debió derivar",
    "respuesta_incorrecta": "Respuesta incorrecta o desactualizada",
    "tono": "Tono o forma",
    "otro": "Otro",
}


def resumir_revisiones(filas: Iterable[Dict]) -> Dict:
    """Cotizaciones validadas sin corrección (con IC 95 %) y errores por categoría.

    Si un chat tiene varias revisiones de su cotización, cuenta la última.
    """
    filas = list(filas)
    ultima_por_chat = {}
    for f in filas:
        if f.get("tipo") in (REVISION_VALIDADA, REVISION_CORREGIDA):
            ultima_por_chat[f["chat_id"]] = f["tipo"]
    revisadas = len(ultima_por_chat)
    validadas = sum(1 for t in ultima_por_chat.values() if t == REVISION_VALIDADA)
    errores: Dict[str, int] = {}
    for f in filas:
        if f.get("tipo") in (REVISION_CORREGIDA, REVISION_ERROR):
            clave = f.get("categoria") or "otro"
            errores[clave] = errores.get(clave, 0) + 1
    return {
        "cotizaciones_revisadas": revisadas,
        "cotizaciones_validadas": validadas,
        "porcentaje_validadas": validadas / revisadas if revisadas else None,
        "ic95": list(clopper_pearson(validadas, revisadas)) if revisadas else None,
        "errores_reportados": sum(errores.values()),
        "errores_por_categoria": dict(sorted(errores.items(), key=lambda kv: -kv[1])),
    }
