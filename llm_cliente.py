"""Cliente de Groq con keys de respaldo y medición de la espera por límites.

Si una key recibe un 429 (límite de uso), la misma llamada se repite con la
siguiente key. La key que falló queda en pausa solo el tiempo que indica Groq:
- límite por minuto (TPM/RPM): unos segundos; vuelve a usarse enseguida;
- límite por día (TPD/RPD): minutos u horas; se salta hasta entonces.

Groq lo informa en el mensaje ("... on tokens per minute (TPM) ... Please try
again in 1.53s") y en el header `retry-after`.

Ninguna key reintenta sola (max_retries=0 en el SDK): los reintentos los hace
este módulo, para poder medir cuánto tiempo se pierde por la cuota. Ese tiempo
(llamadas rechazadas con 429 + esperas) se acumula por hilo y se lee con
`tomar_espera_ms()`; así la latencia del LLM y la espera por cuota se reportan
por separado.

Expone la misma interfaz que el cliente de OpenAI que usa main.py:
`cliente.chat.completions.create(**kwargs)`.
"""

import re
import threading
import time
from typing import Callable, List, Optional, Tuple

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
PAUSA_POR_DEFECTO_S = 60  # si Groq no dice cuánto esperar
ESPERA_MAXIMA_S = 60  # tope de espera por cuota en una llamada; después se propaga el 429
REINTENTOS_TRANSITORIOS = 2  # errores de red o 5xx, en la misma key
_TRANSITORIOS = (APIConnectionError, APITimeoutError, InternalServerError)

_TIPO = re.compile(r"\((TPM|TPD|RPM|RPD)\)")
_ESPERA = re.compile(r"try again in ([\d.hms]+)")
_PARTE = re.compile(r"([\d.]+)(ms|h|m|s)")  # "ms" antes que "m": "840ms" son 0.84 s, no 840 min

# Espera por cuota acumulada en el hilo actual (cada turno corre su llamada en un hilo)
_estado = threading.local()


def sumar_espera_ms(ms: float):
    _estado.espera_ms = getattr(_estado, "espera_ms", 0.0) + ms


def tomar_espera_ms() -> float:
    """Devuelve la espera por cuota acumulada en este hilo y la reinicia."""
    ms = getattr(_estado, "espera_ms", 0.0)
    _estado.espera_ms = 0.0
    return ms


def _segundos(texto: str) -> Optional[float]:
    """'2m7.44s' -> 127.44; '1.53s' -> 1.53; '1h2m' -> 3720; '840ms' -> 0.84."""
    partes = _PARTE.findall(texto or "")
    if not partes:
        return None
    factor = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    return sum(float(n) * factor[u] for n, u in partes)


def leer_limite(error: Exception) -> Tuple[str, float]:
    """(tipo, segundos de espera) de un 429 de Groq.

    tipo: 'TPM', 'TPD', 'RPM', 'RPD' o 'desconocido'.
    """
    mensaje = str(error)
    m = _TIPO.search(mensaje)
    tipo = m.group(1) if m else "desconocido"
    espera = None
    m = _ESPERA.search(mensaje)
    if m:
        espera = _segundos(m.group(1))
    if espera is None:
        respuesta = getattr(error, "response", None)
        try:
            espera = float(respuesta.headers.get("retry-after"))
        except (AttributeError, TypeError, ValueError):
            espera = None
    return tipo, espera if espera is not None else PAUSA_POR_DEFECTO_S


class ClienteGroqConRespaldo:
    def __init__(self, clientes: List[Tuple[str, object]], reloj: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], None] = time.sleep):
        """clientes: [(nombre, cliente_openai), ...] en orden de preferencia."""
        self._clientes = clientes
        self._reloj = reloj
        self._dormir = dormir
        self._pausado_hasta = {nombre: 0.0 for nombre, _ in clientes}
        self.ultimo_usado: Optional[str] = None
        self.chat = self
        self.completions = self

    def _llamar(self, cliente, kwargs):
        """Una key, con reintentos solo para errores transitorios (red, 5xx)."""
        for intento in range(REINTENTOS_TRANSITORIOS + 1):
            try:
                return cliente.chat.completions.create(**kwargs)
            except _TRANSITORIOS:
                if intento == REINTENTOS_TRANSITORIOS:
                    raise
                self._dormir(0.5 * 2 ** intento)

    def _probar(self, candidatos, kwargs):
        """Prueba las keys en orden. Devuelve (respuesta, None) o (None, último 429)."""
        error = None
        for nombre, cliente in candidatos:
            inicio = self._reloj()
            try:
                respuesta = self._llamar(cliente, kwargs)
                self.ultimo_usado = nombre
                return respuesta, None
            except RateLimitError as e:
                sumar_espera_ms((self._reloj() - inicio) * 1000)  # la llamada rechazada también es espera
                tipo, espera = leer_limite(e)
                self._pausado_hasta[nombre] = self._reloj() + espera
                error = e
                print(f"🔀 [LLM] Límite {tipo} en la key {nombre} (libre en {espera:.0f} s)")
        return None, error

    def create(self, **kwargs):
        esperado_s = 0.0
        while True:
            ahora = self._reloj()
            disponibles = [(n, c) for n, c in self._clientes if self._pausado_hasta[n] <= ahora]
            respuesta, _ = self._probar(disponibles, kwargs)
            if respuesta is not None:
                return respuesta
            # Todas las keys en pausa: esperar a la primera que se libere, con tope
            espera = max(min(self._pausado_hasta.values()) - self._reloj(), 0.05)
            if esperado_s + espera > ESPERA_MAXIMA_S:
                # Último intento con todas, aunque estén en pausa: o responde o sale el 429 real
                respuesta, error = self._probar(self._clientes, kwargs)
                if respuesta is not None:
                    return respuesta
                raise error
            print(f"⏳ [LLM] Todas las keys en pausa; espero {espera:.1f} s")
            self._dormir(espera)
            sumar_espera_ms(espera * 1000)
            esperado_s += espera


def keys_de_respaldo(entorno) -> List[str]:
    """GROQ_API_KEY_RESPALDO, GROQ_API_KEY_RESPALDO_2, _3... en ese orden (sin vacías)."""
    nombres = ["GROQ_API_KEY_RESPALDO"] + [f"GROQ_API_KEY_RESPALDO_{i}" for i in range(2, 10)]
    return [entorno.get(n) for n in nombres if entorno.get(n)]


def crear_cliente(key_principal: Optional[str], respaldos: Optional[List[str]] = None) -> ClienteGroqConRespaldo:
    """Envoltorio con la key principal y las de respaldo (si las hay), en orden."""
    keys = [("principal", key_principal)] + [
        (f"respaldo {i}", k) for i, k in enumerate([k for k in (respaldos or []) if k], 1)
    ]
    return ClienteGroqConRespaldo([
        (nombre, OpenAI(api_key=k, base_url=GROQ_BASE_URL, max_retries=0)) for nombre, k in keys
    ])
