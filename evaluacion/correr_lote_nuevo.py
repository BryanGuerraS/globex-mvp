"""Corre el lote nuevo de principio a fin según el pre-registro (un solo comando).

Pasos, en orden y sin intervención manual:
  0. Verifica la huella SHA-256 del lote y los commits: la v0 en su worktree (92859b0) y la v1
     en este checkout, ambos sin cambios en el código del bot.
  1. Convierte el lote con los casos de validación parcial incluidos (se marcan aparte).
  2. Baseline de reglas sin LLM ×1 y su juez.
  3. Globix v1 ×N (este checkout) y su juez por corrida.
  4. Globix v0 ×N (código del worktree de la v0, mismas herramientas de evaluación) y su juez.
  5. Comparación de las tres opciones (comparar_lote_nuevo.py).

Uso (desde la raíz del repo, con el .env que tiene GROQ_API_KEY y GROQ_API_KEY_JUEZ):
    git worktree add --detach .worktrees/v0 92859b0
    python evaluacion/correr_lote_nuevo.py --repeticiones 3

Las herramientas de evaluación (conversor, juez, rúbrica, comparación) son siempre las de este
checkout. `evaluar.py` es idéntico en 92859b0 y en la v1, y para la v0 se ejecuta el de su
worktree para que importe el bot de la v0.
"""

import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOTE = os.path.join(REPO, "evaluacion", "reservado", "lote_nuevo_60", "Globex_Lote_Nuevo_60_Casos_Reales.txt")
SHA_LOTE = "717d4a2f9d5ca09171e4af994dacfdbdb9cdbf36905e0eb27ae06d1d745c4171"
COMMIT_V0 = "92859b0"
CODIGO_BOT = ["main.py", "guardrails.py", "knowledge_base.py", "pricing_engine.py", "validaciones.py",
              "product_catalog.py", "llm_cliente.py", "database.py", "metricas.py", "evaluacion/evaluar.py",
              "evaluacion/baseline_reglas.py"]


def git(repo, *args) -> str:
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def verificar_checkout(repo: str, commit: str) -> str:
    """Hash completo del HEAD; falla si no es el commit esperado o si el bot tiene cambios."""
    head = git(repo, "rev-parse", "HEAD")
    if commit and not head.startswith(git(repo, "rev-parse", commit)[:12]):
        sys.exit(f"{repo} está en {head[:7]}, se esperaba {commit}")
    existentes = [f for f in CODIGO_BOT if os.path.exists(os.path.join(repo, f))]
    if subprocess.call(["git", "-C", repo, "diff", "--quiet", "HEAD", "--", *existentes]) != 0:
        sys.exit(f"{repo} tiene cambios sin commit en el código del bot: congela antes de correr")
    return head


def correr(args, log, cwd=REPO):
    print(f"  -> {' '.join(os.path.basename(a) if a.endswith('.py') else a for a in args)}")
    with open(log, "w", encoding="utf-8") as f:
        codigo = subprocess.call([PY, "-u", *args], cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if codigo != 0:
        sys.exit(f"Falló el paso (código {codigo}). Revisa {log}")


def nuevo_json(carpeta, antes):
    nuevos = sorted(set(glob.glob(os.path.join(carpeta, "resultados_*.json"))) - antes)
    if not nuevos:
        sys.exit(f"No se generó un resultados_*.json en {carpeta}")
    return nuevos[-1]


def corrida(repo_bot, casos, carpeta, log, extra=()):
    os.makedirs(carpeta, exist_ok=True)
    antes = set(glob.glob(os.path.join(carpeta, "resultados_*.json")))
    correr([os.path.join(repo_bot, "evaluacion", "evaluar.py"), "--casos", casos, "--repeticiones", "1",
            "--salida", carpeta, *extra], log, cwd=repo_bot)
    return nuevo_json(carpeta, antes)


def juzgar(resultados, carpeta, log):
    correr([os.path.join(REPO, "evaluacion", "juez_llm.py"), "--resultados", resultados, "--muestra", "100000",
            "--salida", carpeta], log)
    return carpeta


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--v0-repo", default=os.path.join(REPO, ".worktrees", "v0"))
    p.add_argument("--lote", default=LOTE)
    p.add_argument("--salida", default=os.path.join(REPO, "evaluacion", "reportes",
                                                    f"lote_nuevo_{datetime.now():%Y%m%d_%H%M%S}"))
    a = p.parse_args(argv)
    lote, salida, v0_repo = os.path.abspath(a.lote), os.path.abspath(a.salida), os.path.abspath(a.v0_repo)

    print("0. Verificar lote y commits")
    from evaluacion.ficha_repeticiones import sha256  # noqa: E402
    if sha256(lote) != SHA_LOTE:
        sys.exit("La huella SHA-256 del lote no coincide con la del pre-registro")
    verificar_checkout(REPO, "")
    # La v1 es el último commit que tocó el código del bot (los commits de documentación no la cambian)
    commit_v1 = git(REPO, "log", "-1", "--format=%H", "--", *[f for f in CODIGO_BOT if os.path.exists(os.path.join(REPO, f))])
    commit_v0 = verificar_checkout(v0_repo, COMMIT_V0)
    os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, "0_versiones.txt"), "w", encoding="utf-8") as f:
        f.write(f"lote_sha256={SHA_LOTE}\nv1={commit_v1}\nv0={commit_v0}\nherramientas={git(REPO, 'rev-parse', 'HEAD')}\nrepeticiones={a.repeticiones}\n"
                f"inicio={datetime.now():%d/%m/%Y %H:%M:%S}\n")
    print(f"   v1 {commit_v1[:7]} · v0 {commit_v0[:7]} · lote {SHA_LOTE[:12]}…")

    print("1. Convertir el lote (con validación parcial)")
    correr([os.path.join(REPO, "evaluacion", "convertir_banco.py"), lote, "--incluir-parciales"],
           os.path.join(salida, "1_convertir.log"))
    casos = os.path.join(os.path.dirname(lote), "casos_reservados.json")

    print("2. Reglas sin LLM ×1")
    json_r = corrida(REPO, casos, os.path.join(salida, "reglas"), os.path.join(salida, "2_reglas.log"), ["--reglas"])
    juez_r = juzgar(json_r, os.path.join(salida, "juez_reglas"), os.path.join(salida, "2_juez_reglas.log"))

    runs = {"v1": [], "v0": []}
    jueces = {"v1": [], "v0": []}
    for n, (version, repo_bot) in enumerate((("v1", REPO), ("v0", v0_repo)), start=3):
        print(f"{n}. Globix {version} ×{a.repeticiones}")
        for r in range(1, a.repeticiones + 1):
            j = corrida(repo_bot, casos, os.path.join(salida, version), os.path.join(salida, f"{n}_{version}_{r}.log"))
            runs[version].append(j)
            jueces[version].append(juzgar(j, os.path.join(salida, f"juez_{version}_{r}"),
                                          os.path.join(salida, f"{n}_juez_{version}_{r}.log")))

    print("5. Comparación")
    correr([os.path.join(REPO, "evaluacion", "comparar_lote_nuevo.py"), "--casos", casos, "--banco", lote,
            "--v0", *runs["v0"], "--juez-v0", *jueces["v0"], "--v1", *runs["v1"], "--juez-v1", *jueces["v1"],
            "--reglas", json_r, "--juez-reglas", juez_r, "--commit-v1", commit_v1[:7], "--salida", salida],
           os.path.join(salida, "5_comparacion.log"))
    print(f"Listo. Comparación y registros en {salida}")


if __name__ == "__main__":
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    main()
