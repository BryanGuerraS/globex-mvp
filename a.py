import glob
import os
import sqlite3

# Número de Diego Román a eliminar
NUMERO = "51946009879"
DB_FILE = "globex.db"

# 1. Eliminar de la base de datos SQLite
if os.path.exists(DB_FILE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM messages WHERE chat_id LIKE ?", (f"%{NUMERO}%",)
    )
    mensajes_borrados = cursor.rowcount

    cursor.execute("DELETE FROM chats WHERE chat_id LIKE ?", (f"%{NUMERO}%",))
    chats_borrados = cursor.rowcount

    conn.commit()
    conn.close()
    print(
        f"✅ Base de datos: Se eliminó {chats_borrados} chat y {mensajes_borrados} mensajes de Diego."
    )
else:
    print("ℹ️ No existe globex.db.")

# 2. Eliminar PDFs de prueba que se hayan generado para él
for pdf in glob.glob(f"cotizaciones_pdf/*{NUMERO}*.pdf"):
    os.remove(pdf)
    print(f"🧹 PDF eliminado: {pdf}")

print(
    f"\n🚀 ¡Diego Román (+{NUMERO}) fue completamente eliminado de tu sistema!"
)