"""Base de conocimiento ampliada de Globex: 132 preguntas frecuentes con su respuesta orientativa.

Fuente: `conocimiento/respuestas_globex_132.txt` y `conocimiento/preguntas_globex_132.txt`,
preparados por el equipo a partir de consultas reales, flyers y reglas comerciales (14/11/2026).
Cada entrada trae la respuesta para el cliente y los criterios de calidad (indispensable,
no aceptable, orientación al asesor), que también usa la evaluación.

El LLM no redacta estas respuestas: busca candidatas con `buscar` y Globix envía la respuesta
orientativa tal cual, para que el cliente reciba solo texto revisado por el equipo.
"""

import math
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from typing import Dict, List

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conocimiento")
ARCHIVO_RESPUESTAS = os.path.join(CARPETA, "respuestas_globex_132.txt")
ARCHIVO_PREGUNTAS = os.path.join(CARPETA, "preguntas_globex_132.txt")

# Rótulo en el archivo -> campo
CAMPOS = {
    "Respuesta orientativa": "respuesta",
    "Indispensable": "indispensable",
    "Opcional": "opcional",
    "Alternativas aceptables": "alternativas",
    "Aclaración pertinente": "aclaracion",
    "Orientación al asesor": "orientacion_asesor",
    "No aceptable": "no_aceptable",
    "Fuente comercial": "fuente",
}
_ENCABEZADO = re.compile(r"^(G\d{3})\s*(.*)$")
SIN_ASESOR = "No se requiere"
# Fuera de la búsqueda (14/11, decisión del usuario): hablan del "free tax" de Amazon/eBay por la
# alianza, que contradice la regla vigente (7 % de TAX en cualquier tienda si el precio no lo incluye).
# Siguen en el archivo; el equipo actualizará el banco.
EXCLUIDAS = {f"G{n:03d}" for n in range(61, 83)} | {"G084"}

# Respuestas que siempre terminan en el asesor, decida lo que decida el LLM (pedido del usuario, 14/11)
DERIVA_SIEMPRE = {"G126", "G127"}  # reempaque y operaciones físicas con las cajas (regla A17)

# Palabras con que los clientes preguntan por cada FAQ del menú (para que la búsqueda las encuentre)
PALABRAS_KB = {
    "plazos_entrega": "cuánto demora cuántos días tarda en llegar plazo de entrega",
    "entrega_lima": "recojo en Lima oficina delivery domicilio dónde recojo horario",
    "cobertura_provincias": "envían a provincias Arequipa Trujillo Cusco Piura Chiclayo Olva Shalom agencia",
    "como_funciona": "cómo funciona el servicio cómo compro pasos courier",
    "metodos_pago": "cómo pago formas de pago Yape Plin tarjeta transferencia",
}  # inicio de "Orientación al asesor" cuando no hace falta


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def leer_respuestas(ruta: str = ARCHIVO_RESPUESTAS) -> Dict[str, Dict]:
    entradas: Dict[str, Dict] = {}
    actual = None
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            m = _ENCABEZADO.match(linea)
            if m:
                actual = {"id": m.group(1), "tema": m.group(2).strip()}
                entradas[actual["id"]] = actual
                continue
            if actual is None:
                continue
            for rotulo, campo in CAMPOS.items():
                if linea.startswith(rotulo + " "):
                    actual[campo] = linea[len(rotulo) + 1:].strip()
                    break
    return entradas


def leer_preguntas(ruta: str = ARCHIVO_PREGUNTAS) -> Dict[str, str]:
    preguntas: Dict[str, List[str]] = {}
    actual = None
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            m = re.match(r"^(G\d{3})\s*$", linea.strip())
            if m:
                actual = m.group(1)
                preguntas[actual] = []
            elif actual and linea.strip():
                preguntas[actual].append(linea.strip())
    return {k: " ".join(v) for k, v in preguntas.items()}


@lru_cache(maxsize=1)
def entradas() -> Dict[str, Dict]:
    datos = leer_respuestas()
    for gid, pregunta in leer_preguntas().items():
        if gid in datos:
            datos[gid]["pregunta"] = pregunta
    # Las FAQ aprobadas del menú (knowledge_base.py) también son candidatas: cubren datos que
    # las 132 no tienen (por ejemplo, que a provincias solo se envía por Shalom y no por Olva)
    from knowledge_base import KB_GLOBEX
    for tema, faq in KB_GLOBEX.items():
        if tema not in PALABRAS_KB:  # direccion_miami queda fuera hasta aprobar su texto alineado con G001-G005
            continue
        datos[f"KB-{tema}"] = {"id": f"KB-{tema}", "tema": faq["titulo"],
                               "pregunta": f"{faq['titulo']} {PALABRAS_KB[tema]}",
                               "respuesta": faq["contenido"], "orientacion_asesor": SIN_ASESOR + " (FAQ del menú)."}
    return datos


def requiere_asesor(entrada: Dict) -> bool:
    """La entrada indica que, en algún caso, interviene un asesor."""
    return not (entrada.get("orientacion_asesor") or "").startswith(SIN_ASESOR)


# ------------------------------------------------------------------ búsqueda

def _trigramas(texto: str) -> List[str]:
    """Trigramas de caracteres por palabra: toleran faltas ("direcsion", "k llegue")."""
    salida = []
    for palabra in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        p = f" {palabra} "
        salida += [p[i:i + 3] for i in range(len(p) - 2)]
    return salida


@lru_cache(maxsize=1)
def _indice():
    docs = {}
    for gid, e in entradas().items():
        if gid in EXCLUIDAS:
            continue
        # La pregunta y el tema pesan el doble que la respuesta
        texto = " ".join([e.get("pregunta", "")] * 2 + [e.get("tema", "")] * 2 + [e.get("respuesta", "")])
        docs[gid] = Counter(_trigramas(texto))
    n = len(docs)
    df = Counter(t for c in docs.values() for t in c)
    idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}
    vectores = {}
    for gid, c in docs.items():
        v = {t: f * idf[t] for t, f in c.items()}
        norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vectores[gid] = {t: x / norma for t, x in v.items()}
    return vectores, idf


def buscar(pregunta: str, k: int = 4) -> List[Dict]:
    """Las k entradas más parecidas a la pregunta (similitud coseno de trigramas TF-IDF)."""
    vectores, idf = _indice()
    c = Counter(_trigramas(pregunta))
    q = {t: f * idf[t] for t, f in c.items() if t in idf}
    norma = math.sqrt(sum(x * x for x in q.values())) or 1.0
    puntajes = []
    for gid, v in vectores.items():
        s = sum(x * v.get(t, 0.0) for t, x in q.items()) / norma
        puntajes.append((s, gid))
    puntajes.sort(reverse=True)
    datos = entradas()
    return [{**datos[gid], "puntaje": round(s, 3)} for s, gid in puntajes[:k] if s > 0]


def candidatos_para_llm(pregunta: str, k: int = 4) -> List[Dict]:
    """Lo que ve el LLM de cada candidata: lo justo para elegir y decidir si deriva."""
    return [{"id": e["id"], "tema": e["tema"], "pregunta_ejemplo": e.get("pregunta", ""),
             "respuesta": e.get("respuesta", ""), "orientacion_asesor": e.get("orientacion_asesor", "")}
            for e in buscar(pregunta, k)]
