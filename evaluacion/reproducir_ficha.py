"""Reproduce de principio a fin la evaluación de Globix contra el baseline (un solo comando).

Pasos, en orden y sin intervención manual:
  1. Convierte el banco de pruebas (bloques INICIO_CASO) a casos de evaluación.
  2. Corre el baseline de reglas sin LLM (determinista) y lo califica con el juez.
  3. Corre Globix N veces sobre el mismo banco y califica cada corrida con el juez.
  4. Arma la ficha: As-Is, propuesta (promedio), diferencia y mínimo–máximo entre corridas,
     con la huella SHA-256 del banco.

Uso (desde la raíz del repo, con el .env que tiene GROQ_API_KEY y GROQ_API_KEY_JUEZ):
    python evaluacion/reproducir_ficha.py --banco evaluacion/reservado/<banco>.txt --repeticiones 3

Parámetros fijos: temperatura 0.2 (Globix, en main.py) y 0 (juez); semilla 17 del bootstrap
y 7 de la muestra del juez. El LLM de Groq no admite semilla, así que las corridas de Globix
varían: por eso se repiten y se informa el rango. Para reproducir la versión evaluada en el
E5, ejecutar este script en el commit 92859b0 (bot idéntico al de 9acff1f).
"""

import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def correr(args, log):
    """Ejecuta un paso; falla con el log a mano si el paso falla."""
    print(f"  -> {' '.join(os.path.basename(a) if a.endswith('.py') else a for a in args)}")
    with open(log, "w", encoding="utf-8") as f:
        codigo = subprocess.call([PY, "-u", *args], cwd=REPO, stdout=f, stderr=subprocess.STDOUT,
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if codigo != 0:
        sys.exit(f"Falló el paso (código {codigo}). Revisa {log}")


def nuevo_json(carpeta, antes):
    nuevos = sorted(set(glob.glob(os.path.join(carpeta, "resultados_*.json"))) - antes)
    if not nuevos:
        sys.exit(f"No se generó un resultados_*.json en {carpeta}")
    return nuevos[-1]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--banco", required=True, help="Banco de pruebas en formato INICIO_CASO")
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes",
                                                    f"reproduccion_{datetime.now():%Y%m%d_%H%M%S}"))
    p.add_argument("--sin-juez", action="store_true", help="Solo checks automáticos (sin el LLM juez)")
    a = p.parse_args(argv)
    banco = os.path.abspath(a.banco)
    salida = os.path.abspath(a.salida)
    os.makedirs(salida, exist_ok=True)
    casos = os.path.join(os.path.dirname(banco), "casos_reservados.json")

    print("1. Convertir el banco")
    correr([os.path.join(REPO, "evaluacion", "convertir_banco.py"), banco], os.path.join(salida, "1_convertir.log"))

    print("2. Baseline de reglas sin LLM")
    carpeta_b = os.path.join(salida, "baseline")
    os.makedirs(carpeta_b, exist_ok=True)
    antes = set(glob.glob(os.path.join(carpeta_b, "resultados_*.json")))
    correr([os.path.join(REPO, "evaluacion", "evaluar.py"), "--casos", casos, "--repeticiones", "1", "--reglas",
            "--salida", carpeta_b], os.path.join(salida, "2_baseline.log"))
    json_b = nuevo_json(carpeta_b, antes)
    juez_b = None
    if not a.sin_juez:
        juez_b = os.path.join(salida, "juez_baseline")
        correr([os.path.join(REPO, "evaluacion", "juez_llm.py"), "--resultados", json_b, "--muestra", "100000",
                "--salida", juez_b], os.path.join(salida, "2_juez_baseline.log"))

    print(f"3. Globix x{a.repeticiones}")
    carpeta_g = os.path.join(salida, "globix")
    os.makedirs(carpeta_g, exist_ok=True)
    jsons_g, jueces_g = [], []
    for r in range(1, a.repeticiones + 1):
        antes = set(glob.glob(os.path.join(carpeta_g, "resultados_*.json")))
        correr([os.path.join(REPO, "evaluacion", "evaluar.py"), "--casos", casos, "--repeticiones", "1",
                "--salida", carpeta_g], os.path.join(salida, f"3_globix_{r}.log"))
        jsons_g.append(nuevo_json(carpeta_g, antes))
        if not a.sin_juez:
            d = os.path.join(salida, f"juez_globix_{r}")
            correr([os.path.join(REPO, "evaluacion", "juez_llm.py"), "--resultados", jsons_g[-1], "--muestra",
                    "100000", "--salida", d], os.path.join(salida, f"3_juez_globix_{r}.log"))
            jueces_g.append(d)

    print("4. Ficha")
    args = [os.path.join(REPO, "evaluacion", "ficha_repeticiones.py"), "--casos", casos, "--banco", banco,
            "--v0", *jsons_g, "--baseline", json_b, "--salida", salida]
    if jueces_g:
        args += ["--juez-v0", *jueces_g, "--juez-baseline", juez_b]
    correr(args, os.path.join(salida, "4_ficha.log"))
    print(f"Listo. Ficha y registros en {salida}")


if __name__ == "__main__":
    main()
