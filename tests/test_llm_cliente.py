"""Fallback de Groq: ante un 429 de la key principal se usa la de respaldo."""

from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI, RateLimitError

import llm_cliente
from llm_cliente import ClienteGroqConRespaldo, crear_cliente


TPM = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` "
       "on tokens per minute (TPM): Limit 8000, Used 6311, Requested 1893. Please try again in 1.529999999s.")
TPD = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` "
       "on tokens per day (TPD): Limit 200000, Used 198467, Requested 1828. Please try again in 2m7.44s.")


def _error_429(mensaje=TPD, headers=None):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return RateLimitError(mensaje, response=httpx.Response(429, request=req, headers=headers), body=None)


class Falso:
    def __init__(self, nombre, falla=False, error=None):
        self.nombre, self.falla, self.error, self.llamadas = nombre, falla, error, 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.llamadas += 1
        if self.falla:
            raise self.error or _error_429()
        return f"respuesta de {self.nombre}"


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_usa_la_principal_si_responde():
    p, r = Falso("principal"), Falso("respaldo")
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo", r)])
    assert c.chat.completions.create(model="m") == "respuesta de principal"
    assert r.llamadas == 0 and c.ultimo_usado == "principal"


def test_429_pasa_a_respaldo_y_pausa_la_principal():
    reloj = Reloj()
    p, r = Falso("principal", falla=True), Falso("respaldo")
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo", r)], reloj=reloj)
    assert c.create(model="m") == "respuesta de respaldo"
    assert c.create(model="m") == "respuesta de respaldo"
    assert p.llamadas == 1  # en pausa: no se gasta otra llamada fallida
    reloj.t += 128  # TPD: "try again in 2m7.44s"
    p.falla = False
    assert c.create(model="m") == "respuesta de principal"


def test_limite_por_minuto_pausa_solo_unos_segundos():
    reloj = Reloj()
    p, r = Falso("principal", falla=True, error=_error_429(TPM)), Falso("respaldo")
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo", r)], reloj=reloj)
    assert c.create(model="m") == "respuesta de respaldo"
    reloj.t += 2  # TPM: "try again in 1.53s"
    p.falla = False
    assert c.create(model="m") == "respuesta de principal"


@pytest.mark.parametrize("error, tipo, espera", [
    (_error_429(TPM), "TPM", 1.53),
    (_error_429(TPD), "TPD", 127.44),
    (_error_429("... per day (RPD) ... Please try again in 1h2m3s."), "RPD", 3723),
    (_error_429("... per minute (TPM) ... Please try again in 840ms. Need more tokens?"), "TPM", 0.84),
    (_error_429("... per minute (TPM) ... Please try again in 1m2.5s."), "TPM", 62.5),
    (_error_429("limite", headers={"retry-after": "7"}), "desconocido", 7),
    (_error_429("limite"), "desconocido", llm_cliente.PAUSA_POR_DEFECTO_S),
])
def test_leer_limite(error, tipo, espera):
    t, s = llm_cliente.leer_limite(error)
    assert t == tipo and s == pytest.approx(espera, abs=0.01)


def test_si_ambas_tienen_429_propaga_el_error():
    c = ClienteGroqConRespaldo([("principal", Falso("p", falla=True)), ("respaldo", Falso("r", falla=True))])
    with pytest.raises(RateLimitError):
        c.create(model="m")


def test_otros_errores_no_cambian_de_key():
    r = Falso("respaldo")
    c = ClienteGroqConRespaldo([("principal", Falso("p", falla=True, error=ValueError("400"))), ("respaldo", r)])
    with pytest.raises(ValueError):
        c.create(model="m")
    assert r.llamadas == 0


def test_crear_cliente_sin_reintentos_ocultos():
    """Ninguna key reintenta sola en el SDK: las esperas las hace y las mide llm_cliente."""
    solo = crear_cliente("k1", None)
    assert [n for n, _ in solo._clientes] == ["principal"]
    c = crear_cliente("k1", ["k2", "", "k3"])
    assert [n for n, _ in c._clientes] == ["principal", "respaldo 1", "respaldo 2"]
    assert all(x.max_retries == 0 for _, x in c._clientes)


def test_mide_la_espera_por_cuota():
    reloj = Reloj()
    dormidas = []

    def dormir(s):
        dormidas.append(s)
        reloj.t += s

    p, r = Falso("p", falla=True, error=_error_429(TPM)), Falso("r", falla=True, error=_error_429(TPM))
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo", r)], reloj=reloj, dormir=dormir)
    llm_cliente.tomar_espera_ms()

    def libera_tras_esperar(**kw):  # tras la espera, la principal ya responde
        if reloj.t >= 1.5:
            return "ok"
        raise _error_429(TPM)

    p.create = libera_tras_esperar
    assert c.create(model="m") == "ok"
    assert dormidas == [pytest.approx(1.53, abs=0.01)]
    assert llm_cliente.tomar_espera_ms() == pytest.approx(1530, abs=10)
    assert llm_cliente.tomar_espera_ms() == 0  # se reinicia al leerla


def test_espera_con_tope_y_luego_propaga_el_429():
    reloj = Reloj()

    def dormir(s):
        reloj.t += s

    c = ClienteGroqConRespaldo([("principal", Falso("p", falla=True)), ("respaldo", Falso("r", falla=True))],
                               reloj=reloj, dormir=dormir)
    with pytest.raises(RateLimitError):
        c.create(model="m")  # TPD: 127 s > tope de 60 s, no espera
    assert reloj.t == 0


def test_errores_transitorios_reintentan_en_la_misma_key():
    from openai import APIConnectionError
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    p, r = Falso("p"), Falso("r")
    intentos = []

    def inestable(**kw):
        intentos.append(1)
        if len(intentos) < 2:
            raise APIConnectionError(request=req)
        return "ok"

    p.create = inestable
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo", r)], dormir=lambda s: None)
    assert c.create(model="m") == "ok" and r.llamadas == 0


def test_medidor_separa_latencia_y_espera():
    from metricas import MedidorTurno, resumir
    m = MedidorTurno("c1")
    m.registrar_llamada_llm(SimpleNamespace(usage=None), 12000, espera_limite_ms=9000)
    fila = m.fila(12500, 12500)
    assert fila["latencia_llm_ms"] == 3000 and fila["espera_limite_ms"] == 9000
    otra = MedidorTurno("c2").fila(2000, 2000)
    res = resumir([{**fila, "latencia_total_ms": 12500}, {**otra, "llamadas_llm": 0}])
    assert res["espera_limite"]["turnos_afectados"] == 1
    assert res["latencia_total_sin_limites"]["p95_ms"] < res["latencia_total_cliente"]["p95_ms"]


def test_keys_de_respaldo_en_orden():
    entorno = {"GROQ_API_KEY_RESPALDO_2": "b", "GROQ_API_KEY_RESPALDO": "a", "GROQ_API_KEY_RESPALDO_3": ""}
    assert llm_cliente.keys_de_respaldo(entorno) == ["a", "b"]


def test_tres_keys_pasa_a_la_tercera():
    p, r1, r2 = Falso("p", falla=True), Falso("r1", falla=True), Falso("r2")
    c = ClienteGroqConRespaldo([("principal", p), ("respaldo 1", r1), ("respaldo 2", r2)])
    assert c.create(model="m") == "respuesta de r2" and c.ultimo_usado == "respaldo 2"
