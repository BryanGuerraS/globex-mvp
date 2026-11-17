"""scripts/datos_demo.py crea una base demo con conversaciones sintéticas para la consola."""

import importlib.util
from pathlib import Path


def test_datos_demo_crea_chats_con_cotizacion_y_resumen(tmp_path, monkeypatch):
    import database
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("datos_demo", repo / "scripts" / "datos_demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    base = str(tmp_path / "demo.db")
    original = database.DB_FILE
    try:
        assert demo.poblar(base) == ["DEMO-0001", "DEMO-0002", "DEMO-0003", "DEMO-0004"]
        chats = {c["chat_id"]: c for c in database.obtener_todos_los_chats()}
        assert chats["DEMO-0001"]["cotizacion_total"] > 0
        derivado = database.obtener_chat("DEMO-0002")
        assert derivado["bot_activo"] == 0 and "*Motivo:* Pidió hablar con un asesor" in derivado["resumen_caso"]
        assert "zapatillas Nike" in derivado["resumen_caso"]
    finally:
        database.DB_FILE = original
        monkeypatch.delenv("GLOBEX_DB", raising=False)
