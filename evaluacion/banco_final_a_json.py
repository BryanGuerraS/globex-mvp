"""Convierte el banco final del equipo (Globex_Bancos_V2: Preguntas.txt, Cotizaciones.txt, Chats.txt) al
formato de ejecución GLOBEX_BANCO_EJECUCION_1 que usan correr_banco_api.py y juez_banco.py.

Uso: python evaluacion/banco_final_a_json.py <carpeta Globex_Bancos_V2> <salida.json>

No muestra el contenido de las preguntas: solo valida que los ids coincidan con 00_Indice_Bancos.txt.
"""

import json
import re
import sys
from pathlib import Path

ARCHIVOS = {"FAQ": "02_FAQ/Preguntas.txt", "DERIVACION": "03_Derivacion/Preguntas.txt",
            "PRODUCTOS": "04_Productos_Especiales/Preguntas.txt", "COTIZACIONES": "06_Cotizaciones/Cotizaciones.txt",
            "CHATS_COMPARTIDOS": "05_Chats_Recopilacion_Resumen/Chats.txt"}


def bloques(texto: str):
    for bloque in re.split(r"\n\s*\n", texto.strip()):
        lineas = [l.strip() for l in bloque.splitlines() if l.strip()]
        m = re.match(r"ID\s*:\s*(\S+)", lineas[0]) if lineas else None
        if m:
            yield m.group(1), lineas[1:]


def convertir(carpeta: Path) -> dict:
    indice = json.loads((carpeta / "00_Indice_Bancos.txt").read_text(encoding="utf-8"))
    casos = []
    for banco in indice["bancos"]:
        nombre = banco["banco"]
        texto = (carpeta / ARCHIVOS[nombre]).read_text(encoding="utf-8")
        leidos = {}
        for cid, lineas in bloques(texto):
            universo = None
            if lineas and lineas[0].startswith("UNIVERSO"):
                universo = lineas[0].split(":", 1)[1].strip()
                lineas = lineas[1:]
            caso = {"id": cid, "banco": nombre, "universo": universo, "banco_id": banco["banco_id"],
                    "version_banco": indice.get("version_paquete")}
            mensajes = [re.sub(r"^MENSAJE\s*\d+\s*:\s*", "", l) for l in lineas]
            if nombre == "CHATS_COMPARTIDOS":
                caso["mensajes"] = mensajes
            else:
                caso["pregunta"] = " ".join(mensajes)
            leidos[cid] = caso
        previstos = banco["ids_previstos"]
        faltan = [i for i in previstos if i not in leidos]
        sobran = [i for i in leidos if i not in previstos]
        if faltan or sobran:
            sys.exit(f"{nombre}: ids que no coinciden con el índice (faltan {faltan}, sobran {sobran})")
        casos += [leidos[i] for i in previstos]
    productos = next(b for b in indice["bancos"] if b["banco"] == "PRODUCTOS")
    return {"schema_version": "GLOBEX_BANCO_EJECUCION_1", "version_paquete": indice.get("version_paquete"),
            "finalidad": "BANCO_FINAL_DE_METRICAS", "ids_bloqueados_productos": productos.get("ids_bloqueados_previstos", []),
            "casos": casos}


if __name__ == "__main__":
    datos = convertir(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(len(datos["casos"]), dict(Counter(c["banco"] for c in datos["casos"])),
          "bloqueados:", len(datos["ids_bloqueados_productos"]),
          "turnos chats:", dict(Counter(len(c["mensajes"]) for c in datos["casos"] if "mensajes" in c)))
