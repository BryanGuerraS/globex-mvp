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
import os
import statistics
from typing import Dict, Iterable, List, Optional

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
        self.herramientas: List[Dict] = []
        self.tipo_respuesta = "libre"

    def registrar_llamada_llm(self, respuesta, ms: float):
        self.llamadas_llm += 1
        self.latencia_llm_ms += ms
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
        "tipos_respuesta": tipos,
        "precio_usd_por_millon": {"entrada": PRECIO_ENTRADA_USD_M, "salida": PRECIO_SALIDA_USD_M},
    }
