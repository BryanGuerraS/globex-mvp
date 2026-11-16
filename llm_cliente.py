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

from openai import APIConnectionError, APIStatusError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"  # misma API compatible con OpenAI
PAUSA_POR_DEFECTO_S = 60  # si Groq no dice cuánto esperar
PAUSA_KEY_INVALIDA_S = 6 * 3600  # key sin créditos o revocada: no se reintenta en horas
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
    def __init__(self, clientes: List[Tuple], reloj: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], None] = time.sleep):
        """clientes: [(nombre, cliente_openai), ...] o [(nombre, cliente_openai, modelo), ...] en orden de
        preferencia. Con modelo, esa key usa su propio nombre de modelo (proveedores mezclados)."""
        self._modelos = {c[0]: c[2] for c in clientes if len(c) > 2 and c[2]}
        clientes = [(c[0], c[1]) for c in clientes]
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
                respuesta = self._llamar(cliente, {**kwargs, "model": self._modelos[nombre]}
                                         if nombre in self._modelos else kwargs)
                self.ultimo_usado = nombre
                return respuesta, None
            except RateLimitError as e:
                sumar_espera_ms((self._reloj() - inicio) * 1000)  # la llamada rechazada también es espera
                tipo, espera = leer_limite(e)
                self._pausado_hasta[nombre] = self._reloj() + espera
                error = e
                print(f"🔀 [LLM] Límite {tipo} en la key {nombre} (libre en {espera:.0f} s)")
            except APIStatusError as e:
                # Key sin créditos (402), revocada o sin permiso (401/403): se aparta varias horas y se usa la
                # siguiente; antes cortaba la llamada aunque hubiera otras keys (16/11, key gratuita agotada)
                if e.status_code not in (401, 402, 403):
                    raise
                self._pausado_hasta[nombre] = self._reloj() + PAUSA_KEY_INVALIDA_S
                error = e
                print(f"🔀 [LLM] La key {nombre} no se puede usar ({e.status_code}); paso a la siguiente")
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


def keys_de_respaldo(entorno, prefijo: str = "GROQ_API_KEY") -> List[str]:
    """<prefijo>_RESPALDO, <prefijo>_RESPALDO_2, _3... en ese orden (sin vacías)."""
    nombres = [f"{prefijo}_RESPALDO"] + [f"{prefijo}_RESPALDO_{i}" for i in range(2, 21)]
    return [entorno.get(n) for n in nombres if entorno.get(n)]


def crear_cliente_mixto(grupos: List[Tuple[str, List[str], str, str]]) -> ClienteGroqConRespaldo:
    """Varias keys de distintos proveedores en un solo cliente, en orden.

    grupos: [(prefijo, keys, base_url, modelo), ...]; cada key usa el modelo de su proveedor.
    """
    clientes = []
    for prefijo, keys, base_url, modelo in grupos:
        for i, k in enumerate([k for k in keys if k], 1):
            clientes.append((f"{prefijo} {i}", OpenAI(api_key=k, base_url=base_url, max_retries=0), modelo))
    return ClienteGroqConRespaldo(clientes)


def crear_cliente(key_principal: Optional[str], respaldos: Optional[List[str]] = None,
                  base_url: str = GROQ_BASE_URL) -> ClienteGroqConRespaldo:
    """Envoltorio con la key principal y las de respaldo (si las hay), en orden."""
    keys = [("principal", key_principal)] + [
        (f"respaldo {i}", k) for i, k in enumerate([k for k in (respaldos or []) if k], 1)
    ]
    return ClienteGroqConRespaldo([
        (nombre, OpenAI(api_key=k, base_url=base_url, max_retries=0)) for nombre, k in keys
    ])
