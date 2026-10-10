from datetime import datetime
import sqlite3
from typing import Dict, List, Optional

DB_FILE = "globex.db"


def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa y migra las tablas con los nuevos campos de negocio."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Tabla de Chats / Leads
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                nombre TEXT,
                tipo_contacto TEXT DEFAULT '🌱 Prospecto Nuevo',
                servicio TEXT DEFAULT 'Cotización Courier',
                producto TEXT,
                cotizacion_total REAL,
                asesor_asignado TEXT,
                estado TEXT DEFAULT 'Atendido por Bot',
                paso_happy_path INTEGER DEFAULT 1,
                bot_activo INTEGER DEFAULT 1,
                recordatorio_enviado INTEGER DEFAULT 0,
                ultimo_mensaje_cliente_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """
        )

        # 2. Tabla de Mensajes (con id_mensaje único para deduplicación HP01)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_mensaje TEXT UNIQUE,
                chat_id TEXT,
                emisor TEXT,
                texto TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
            )
        """
        )

        # 3. Migraciones seguras para chats (por si la BD ya existía)
        cursor.execute("PRAGMA table_info(chats)")
        columnas = [row["name"] for row in cursor.fetchall()]

        if "tipo_contacto" not in columnas:
            cursor.execute(
                "ALTER TABLE chats ADD COLUMN tipo_contacto TEXT DEFAULT '🌱 Prospecto Nuevo'"
            )
        if "servicio" not in columnas:
            cursor.execute(
                "ALTER TABLE chats ADD COLUMN servicio TEXT DEFAULT 'Cotización Courier'"
            )
        if "ultimo_mensaje_cliente_at" not in columnas:
            cursor.execute(
                "ALTER TABLE chats ADD COLUMN ultimo_mensaje_cliente_at TIMESTAMP"
            )
        if "recordatorio_enviado" not in columnas:
            cursor.execute(
                "ALTER TABLE chats ADD COLUMN recordatorio_enviado INTEGER DEFAULT 0"
            )

        # 4. Migración segura para messages
        cursor.execute("PRAGMA table_info(messages)")
        cols_msg = [row["name"] for row in cursor.fetchall()]
        if "id_mensaje" not in cols_msg:
            cursor.execute("ALTER TABLE messages ADD COLUMN id_mensaje TEXT")

        conn.commit()


def obtener_chats_para_recordatorio() -> List[Dict]:
    """Busca leads que cotizaron, llevan más de 20 min en silencio y no han recibido recordatorio."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM chats 
            WHERE estado = 'Atendido por Bot'
              AND cotizacion_total > 0
              AND recordatorio_enviado = 0
              AND bot_activo = 1
        """)
        return [dict(row) for row in cursor.fetchall()]


def marcar_recordatorio_enviado(chat_id: str):
    """Marca el lead para no enviarle recordatorios repetidos."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chats SET recordatorio_enviado = 1 WHERE chat_id = ?",
            (chat_id,),
        )
        conn.commit()


def calcular_tiempo_relativo(dt_str: Optional[str]) -> Dict[str, str]:
    """Calcula el tiempo transcurrido y devuelve un texto amigable con color de semáforo."""
    if not dt_str:
        return {"texto": "Sin actividad", "color": "gray", "minutos": 0}

    try:
        if isinstance(dt_str, str):
            dt_clean = dt_str.split(".")[0]
            dt = datetime.strptime(dt_clean, "%Y-%m-%d %H:%M:%S")
        else:
            dt = dt_str

        diferencia = datetime.now() - dt
        minutos = int(diferencia.total_seconds() / 60)

        if minutos < 1:
            texto = "Hace un momento"
        elif minutos < 60:
            texto = f"Hace {minutos} min"
        elif minutos < 1440:
            horas = minutos // 60
            texto = f"Hace {horas} h"
        else:
            dias = minutos // 1440
            texto = f"Hace {dias} d"

        if minutos < 15:
            color = "🟢"
        elif minutos <= 45:
            color = "🟡"
        else:
            color = "🔴"

        return {"texto": texto, "color": color, "minutos": minutos}
    except Exception:
        return {"texto": "Reciente", "color": "🟢", "minutos": 0}


def registrar_mensaje_entrante(chat_id: str, nombre: str, texto: str):
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute(
            """
            INSERT INTO chats (chat_id, nombre, updated_at, ultimo_mensaje_cliente_at, asesor_asignado)
            VALUES (?, ?, ?, ?, 'Carlos (Asesor 1)')
            ON CONFLICT(chat_id) DO UPDATE SET 
                nombre = excluded.nombre,
                updated_at = excluded.updated_at,
                ultimo_mensaje_cliente_at = excluded.ultimo_mensaje_cliente_at
        """,
            (chat_id, nombre, now, now),
        )

        cursor.execute(
            """
            INSERT INTO messages (chat_id, emisor, texto, timestamp)
            VALUES (?, 'cliente', ?, ?)
        """,
            (chat_id, texto, now),
        )

        conn.commit()


def registrar_mensaje_saliente(
    chat_id: str, emisor: str, texto: str, cotizacion: Optional[Dict] = None
):
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute(
            """
            INSERT INTO messages (chat_id, emisor, texto, timestamp)
            VALUES (?, ?, ?, ?)
        """,
            (chat_id, emisor, texto, now),
        )

        if cotizacion:
            cursor.execute(
                """
                UPDATE chats SET 
                    producto = ?,
                    cotizacion_total = ?,
                    paso_happy_path = 3,
                    servicio = 'Cotización Courier',
                    updated_at = ?
                WHERE chat_id = ?
            """,
                (
                    f"Envío de {cotizacion.get('peso_kg', 0)} kg",
                    cotizacion.get("costo_total", 0.0),
                    now,
                    chat_id,
                ),
            )
        else:
            cursor.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?",
                (now, chat_id),
            )

        conn.commit()


def actualizar_clasificacion_chat(
    chat_id: str, servicio: str = None, estado: str = None, paso: int = None
):
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = []
        params = []

        if servicio:
            updates.append("servicio = ?")
            params.append(servicio)
        if estado:
            updates.append("estado = ?")
            params.append(estado)
        if paso:
            updates.append("paso_happy_path = ?")
            params.append(paso)

        if updates:
            params.append(chat_id)
            query = f"UPDATE chats SET {', '.join(updates)}, updated_at = ? WHERE chat_id = ?"
            params.insert(len(params) - 1, datetime.now())
            cursor.execute(query, params)
            conn.commit()


def alternar_tipo_cliente(chat_id: str):
    """Cambia entre Prospecto y Cliente Frecuente."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tipo_contacto FROM chats WHERE chat_id = ?", (chat_id,)
        )
        row = cursor.fetchone()
        if row:
            actual = row["tipo_contacto"]
            nuevo = (
                "⭐ Cliente Frecuente"
                if "Prospecto" in actual
                else "🌱 Prospecto Nuevo"
            )
            cursor.execute(
                "UPDATE chats SET tipo_contacto = ? WHERE chat_id = ?",
                (nuevo, chat_id),
            )
            conn.commit()


def actualizar_estado_chat(
    chat_id: str,
    nuevo_estado: str,
    nuevo_asesor: str = None,
    bot_activo: int = None,
):
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "UPDATE chats SET estado = ?"
        params = [nuevo_estado]

        if nuevo_asesor:
            query += ", asesor_asignado = ?"
            params.append(nuevo_asesor)
        if bot_activo is not None:
            query += ", bot_activo = ?"
            params.append(bot_activo)

        query += " WHERE chat_id = ?"
        params.append(chat_id)
        cursor.execute(query, params)
        conn.commit()


def obtener_todos_los_chats() -> List[Dict]:
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chats ORDER BY updated_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def obtener_mensajes_chat(chat_id: str) -> List[Dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC",
            (chat_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

def esta_bot_activo(chat_id: str) -> bool:
    """Verifica si el bot tiene autorización para responder automáticamente."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT bot_activo FROM chats WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row is None:
            return True  # Si es un chat nuevo, el bot inicia activo
        return bool(row["bot_activo"])

def obtener_chats_para_recordatorio() -> List[Dict]:
    """Busca leads que cotizaron, llevan más de 20 min en silencio y no han recibido recordatorio."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        # Busca chats atendidos por bot, con cotización, donde hayan pasado al menos 20 minutos
        cursor.execute("""
            SELECT * FROM chats 
            WHERE estado = 'Atendido por Bot'
              AND cotizacion_total > 0
              AND recordatorio_enviado = 0
              AND bot_activo = 1
        """)
        return [dict(row) for row in cursor.fetchall()]


def marcar_recordatorio_enviado(chat_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chats SET recordatorio_enviado = 1 WHERE chat_id = ?",
            (chat_id,),
        )
        conn.commit()


def es_mensaje_duplicado(id_mensaje: str) -> bool:
    """Verifica si este mensaje exacto de WhatsApp ya fue procesado antes (HP01 / T28)."""
    if not id_mensaje:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM messages WHERE id_mensaje = ?", (id_mensaje,)
        )
        return cursor.fetchone() is not None


def registrar_mensaje_entrante(
    chat_id: str, nombre: str, texto: str, id_mensaje: str = None
):
    init_db()

    # Si ya lo registramos, lo ignoramos para evitar duplicados en la pantalla
    if id_mensaje and es_mensaje_duplicado(id_mensaje):
        return False

    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute(
            """
            INSERT INTO chats (chat_id, nombre, updated_at, ultimo_mensaje_cliente_at, asesor_asignado)
            VALUES (?, ?, ?, ?, 'Carlos (Asesor 1)')
            ON CONFLICT(chat_id) DO UPDATE SET 
                nombre = excluded.nombre,
                updated_at = excluded.updated_at,
                ultimo_mensaje_cliente_at = excluded.ultimo_mensaje_cliente_at
        """,
            (chat_id, nombre, now, now),
        )

        cursor.execute(
            """
            INSERT INTO messages (id_mensaje, chat_id, emisor, texto, timestamp)
            VALUES (?, ?, 'cliente', ?, ?)
        """,
            (id_mensaje, chat_id, texto, now),
        )

        conn.commit()
    return True