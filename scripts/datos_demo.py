"""Datos demo para probar la consola de asesores sin WhatsApp.

Crea una base SQLite con conversaciones SINTÉTICAS (nombres y mensajes inventados) que pasan por el
mismo código del sistema: validación de los datos, motor de cotización, borrador del pedido, control de
mercancía y resumen del caso para el asesor.

Uso (desde la raíz del repositorio):
    python scripts/datos_demo.py                      # crea globex_demo.db
    python scripts/datos_demo.py --base otra.db --reiniciar

Después, backend y consola con esa base: definir GLOBEX_DB=globex_demo.db (ver README, "Prueba local").
"""

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _chat(db, chat_id: str, nombre: str, mensajes):
    """Registra la conversación: [("cliente"|"bot", texto, cotizacion_o_None), ...]."""
    for i, (emisor, texto, cotizacion) in enumerate(mensajes):
        if emisor == "cliente":
            db.registrar_mensaje_entrante(chat_id, nombre, texto, id_mensaje=f"{chat_id}-{i}")
        else:
            db.registrar_mensaje_saliente(chat_id, "bot", texto, cotizacion)


def poblar(base: str, reiniciar: bool = False) -> list:
    if reiniciar and Path(base).exists():
        Path(base).unlink()
    os.environ["GLOBEX_DB"] = base
    import database as db
    db.DB_FILE = base
    db.init_db()
    import borrador
    from guardrails import verificar_mercancia_restringida
    from knowledge_base import KB_GLOBEX
    from pricing_engine import GlobexPricingEngine
    from resumen_caso import construir_resumen
    from validaciones import validar_productos

    creados = []

    # 1. Cotización completa en un mensaje
    texto = "Hola, quiero traer una laptop Lenovo de 650 dólares que pesa 2.5 kg"
    bruto = {"producto": "laptop Lenovo", "precio_unitario_usd": 650, "peso_kg": 2.5}
    productos, _ = validar_productos({"productos": [bruto]}, [texto])
    calculo = GlobexPricingEngine.calcular_pedido(productos)
    _chat(db, "DEMO-0001", "Cliente demo 1", [
        ("cliente", texto, None),
        ("bot", GlobexPricingEngine.formatear_mensaje_whatsapp(calculo), {**calculo, "peso_kg": 2.5}),
    ])
    borrador.guardar("DEMO-0001", borrador.construir(productos, [bruto], None, textos=[texto]),
                     cotizacion={"aceptada": True, "total_usd": calculo["costo_total"]})
    db.marcar_atencion_util("DEMO-0001", "bot", "cotizacion")
    creados.append("DEMO-0001")

    # 2. Pedido de dos productos y pedido de asesor: queda derivado con su resumen
    textos = ["Soy Ana Demo. Quiero unas zapatillas Nike de USD 120 (1.2 kg) y un polo de USD 25 (0.3 kg)",
              "Prefiero que un asesor revise mi pedido, por favor"]
    brutos = [{"producto": "zapatillas Nike", "precio_unitario_usd": 120, "peso_kg": 1.2},
              {"producto": "polo", "precio_unitario_usd": 25, "peso_kg": 0.3}]
    productos, _ = validar_productos({"productos": brutos}, textos)
    calculo = GlobexPricingEngine.calcular_pedido(productos)
    _chat(db, "DEMO-0002", "Cliente demo 2", [
        ("cliente", textos[0], None),
        ("bot", GlobexPricingEngine.formatear_mensaje_whatsapp(calculo), {**calculo, "peso_kg": 1.5}),
        ("cliente", textos[1], None),
        ("bot", "Listo 😊 Un asesor de Globex revisará tu pedido y te escribirá por este chat.", None),
    ])
    borrador.guardar("DEMO-0002", borrador.construir(productos, brutos, None, textos=textos),
                     cotizacion={"aceptada": True, "total_usd": calculo["costo_total"]})
    db.guardar_nombre_cliente("DEMO-0002", "Ana Demo")
    db.actualizar_estado_chat("DEMO-0002", nuevo_estado="Listo para Asesor", bot_activo=0)
    db.guardar_derivacion("DEMO-0002", "asesor", construir_resumen("DEMO-0002", "asesor"))
    db.marcar_atencion_util("DEMO-0002", "bot", "cotizacion")
    creados.append("DEMO-0002")

    # 3. Pregunta frecuente
    _chat(db, "DEMO-0003", "Cliente demo 3", [
        ("cliente", "¿Cuál es la dirección de su almacén en Miami?", None),
        ("bot", KB_GLOBEX["direccion_miami"]["contenido"], None),
    ])
    db.marcar_atencion_util("DEMO-0003", "bot", "faq")
    creados.append("DEMO-0003")

    # 4. Mercancía prohibida
    texto = "Quiero importar unos vapes"
    alerta = verificar_mercancia_restringida(texto)
    _chat(db, "DEMO-0004", "Cliente demo 4", [("cliente", texto, None),
                                              ("bot", (alerta or {}).get("mensaje", ""), None)])
    db.marcar_atencion_util("DEMO-0004", "bot", "guardrail")
    creados.append("DEMO-0004")
    return creados


def main():
    p = argparse.ArgumentParser(description="Crea una base demo con conversaciones sintéticas.")
    p.add_argument("--base", default="globex_demo.db")
    p.add_argument("--reiniciar", action="store_true", help="borra la base demo antes de crearla")
    a = p.parse_args()
    chats = poblar(a.base, a.reiniciar)
    print(f"Base demo {a.base}: {len(chats)} conversaciones sintéticas ({', '.join(chats)})")


if __name__ == "__main__":
    main()
