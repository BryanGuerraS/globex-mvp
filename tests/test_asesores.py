"""Asignación de asesor y nombres de tipo de contacto."""

from fastapi.testclient import TestClient

import database
import main

API = {"X-API-Key": "key_de_prueba"}


def test_chat_nuevo_sin_asesor_y_tipo_profesional():
    main.registrar_mensaje_entrante("PE.6001", "Ana", "hola")
    chat = main.obtener_chat("PE.6001")
    assert chat["asesor_asignado"] is None
    assert chat["tipo_contacto"] == "Nuevo prospecto"


def test_primer_asesor_que_responde_queda_asignado():
    main.registrar_mensaje_entrante("PE.6002", "Ana", "hola")
    cliente = TestClient(main.app)
    r = cliente.post("/api/send-advisor-message", headers=API,
                     json={"chat_id": "PE.6002", "nombre_asesor": "Juan", "texto": "Hola, soy Juan"})
    assert r.status_code == 200
    chat = main.obtener_chat("PE.6002")
    assert chat["asesor_asignado"] == "Juan" and chat["bot_activo"] == 0
    # Otro asesor que escribe después no le quita la asignación
    cliente.post("/api/send-advisor-message", headers=API,
                 json={"chat_id": "PE.6002", "nombre_asesor": "Anyela", "texto": "Te apoyo yo"})
    assert main.obtener_chat("PE.6002")["asesor_asignado"] == "Juan"


def test_asignar_asesor_sin_tocar_bot():
    main.registrar_mensaje_entrante("PE.6003", "Ana", "hola")
    cliente = TestClient(main.app)
    r = cliente.post("/api/update-chat-status", headers=API,
                     json={"chat_id": "PE.6003", "nuevo_estado": "Atendido por Bot", "nuevo_asesor": "Anyela"})
    assert r.status_code == 200
    chat = main.obtener_chat("PE.6003")
    assert chat["asesor_asignado"] == "Anyela" and chat["bot_activo"] == 1


def test_migracion_de_valores_antiguos():
    main.registrar_mensaje_entrante("PE.6004", "Ana", "hola")
    with database.get_connection() as c:
        c.execute("UPDATE chats SET tipo_contacto='🌱 Prospecto Nuevo', asesor_asignado='Carlos (Asesor 1)' WHERE chat_id='PE.6004'")
        c.commit()
    database.init_db()
    chat = main.obtener_chat("PE.6004")
    assert chat["tipo_contacto"] == "Nuevo prospecto" and chat["asesor_asignado"] is None


def test_alternar_tipo_de_contacto():
    main.registrar_mensaje_entrante("PE.6005", "Ana", "hola")
    database.alternar_tipo_cliente("PE.6005")
    assert main.obtener_chat("PE.6005")["tipo_contacto"] == "Cliente recurrente"
    database.alternar_tipo_cliente("PE.6005")
    assert main.obtener_chat("PE.6005")["tipo_contacto"] == "Nuevo prospecto"
