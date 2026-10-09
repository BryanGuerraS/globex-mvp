import sqlite3

conn = sqlite3.connect("globex.db")
cursor = conn.cursor()

# Retrocedemos el reloj 25 minutos y reseteamos el flag de recordatorio
cursor.execute("""
    UPDATE chats 
    SET ultimo_mensaje_cliente_at = datetime('now', '-25 minutes', 'localtime'),
        recordatorio_enviado = 0
    WHERE cotizacion_total > 0
""")
conn.commit()

print("⏳ Reloj retrasado 25 minutos con éxito en SQLite.")