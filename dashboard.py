from datetime import datetime
import os
from dotenv import load_dotenv
import httpx
import streamlit as st

load_dotenv()

# URL base del Backend en Render
BACKEND_URL = os.getenv("BACKEND_URL", "https://globex-mvp.onrender.com")

st.set_page_config(
    page_title="Globex | Panel de Asesores Pro",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

USUARIOS = {
    "diego": {"nombre": "Diego (Director)", "password": "123", "rol": "admin"},
    "carlos": {
        "nombre": "Carlos (Asesor 1)",
        "password": "123",
        "rol": "asesor",
    },
    "maria": {"nombre": "María (Asesor 2)", "password": "123", "rol": "asesor"},
    "juan": {"nombre": "Juan (Asesor 3)", "password": "123", "rol": "asesor"},
    "bryan": {"nombre": "Bryan (Asesor 4)", "password": "123", "rol": "asesor"},
}

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None

if not st.session_state.autenticado:
    st.markdown(
        "<h2 style='text-align: center;'>📦 Globex Courier</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center;'>Panel Operativo de Asesores Comerciales</p>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            usuario_input = st.text_input("Usuario:").strip().lower()
            password_input = st.text_input("Contraseña:", type="password")
            submit = st.form_submit_button("Ingresar")

            if submit:
                if (
                    usuario_input in USUARIOS
                    and USUARIOS[usuario_input]["password"] == password_input
                ):
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = USUARIOS[usuario_input]
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas (Usa: carlos / 123)")
    st.stop()

usuario = st.session_state.usuario_actual


# Funciones de consulta a la API de Render
def fetch_chats():
    try:
        r = httpx.get(f"{BACKEND_URL}/api/chats", timeout=10.0)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def fetch_messages(chat_id):
    try:
        r = httpx.get(f"{BACKEND_URL}/api/messages/{chat_id}", timeout=10.0)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def calcular_tiempo_relativo_ui(dt_str):
    if not dt_str:
        return {"texto": "Sin actividad", "color": "gray"}
    try:
        dt_clean = str(dt_str).split(".")[0]
        dt = datetime.strptime(dt_clean, "%Y-%m-%d %H:%M:%S")
        minutos = int((datetime.now() - dt).total_seconds() / 60)
        if minutos < 1:
            texto = "Hace un momento"
        elif minutos < 60:
            texto = f"Hace {minutos} min"
        elif minutos < 1440:
            texto = f"Hace {minutos // 60} h"
        else:
            texto = f"Hace {minutos // 1440} d"

        color = "🟢" if minutos < 15 else "🟡" if minutos <= 45 else "🔴"
        return {"texto": texto, "color": color}
    except Exception:
        return {"texto": "Reciente", "color": "🟢"}


# ----------------- 2. BARRA LATERAL (SIDEBAR) -----------------
with st.sidebar:
    st.title("📦 Menú Globex")
    st.write(f"👤 **Sesión:** {usuario['nombre']}")
    if st.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.session_state.usuario_actual = None
        st.rerun()

    st.markdown("---")
    st.markdown("### Métricas Operativas")
    chats = fetch_chats()
    st.metric("Total Chats", len(chats))
    listos = sum(1 for c in chats if c.get("estado") == "Listo para Asesor")
    st.metric("Requieren Asesor 🎯", listos)

    st.markdown("---")
    auto_refresh = st.checkbox("⚡ Auto-actualizar mensajes", value=True)

    # 🧹 LIMPIEZA DE DATOS Y PDFs (SOLO ADMIN / DIEGO)
    if usuario.get("rol") == "admin":
        st.markdown("---")
        st.markdown("### Administración")
        if st.button("🗑️ Limpiar Base de Datos y PDFs"):
            try:
                res = httpx.post(f"{BACKEND_URL}/api/admin/clean-data", timeout=10.0)
                if res.status_code == 200:
                    info = res.json()
                    st.success(
                        f"¡Limpieza exitosa! {info.get('pdfs_borrados', 0)} PDFs borrados."
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


# ----------------- 3. REPRODUCTOR DE MENSAJES EN TIEMPO REAL -----------------
@st.fragment(run_every=3.0 if auto_refresh else None)
def renderizar_mensajes_vivos(chat_id_seleccionado: str):
    mensajes = fetch_messages(chat_id_seleccionado)
    chat_box = st.container(height=350)
    with chat_box:
        for m in mensajes:
            if m["emisor"] == "cliente":
                with st.chat_message("user"):
                    st.write(m["texto"])
            elif "bot" in m["emisor"].lower():
                with st.chat_message("assistant"):
                    st.markdown(f"🤖 *(Bot)* {m['texto']}")
            else:
                with st.chat_message("assistant"):
                    st.markdown(f"👨‍💼 *({m['emisor']})* {m['texto']}")


# ----------------- 4. FILTROS SUPERIORES -----------------
col1, col2, col3, col_ref = st.columns([2, 2, 2, 1])
with col1:
    filtro_estado = st.selectbox(
        "Estado:", ["Todos", "Atendido por Bot", "Listo para Asesor", "Cerrado"]
    )
with col2:
    filtro_asesor = st.selectbox(
        "Asesor:",
        [
            "Todos",
            "Carlos (Asesor 1)",
            "María (Asesor 2)",
            "Juan (Asesor 3)",
            "Bryan (Asesor 4)",
        ],
    )
with col3:
    filtro_servicio = st.selectbox(
        "Servicio / Modalidad:",
        [
            "Todos",
            "Cotización Courier",
            "Seguimiento Courier",
            "Cotización Viajero",
            "Seguimiento Viajero",
            "Restringido (DIGEMID)",
            "Mercancía Prohibida",
        ],
    )
with col_ref:
    st.write("")
    st.write("")
    if st.button("🔄 Refrescar"):
        st.rerun()

chats_filtrados = chats
if filtro_estado != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c.get("estado") == filtro_estado
    ]
if filtro_asesor != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c.get("asesor_asignado") == filtro_asesor
    ]
if filtro_servicio != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c.get("servicio") == filtro_servicio
    ]

st.markdown("---")

# ----------------- 5. CUADRÍCULA DE TARJETAS -----------------
if not chats_filtrados:
    st.info("No hay chats con los filtros seleccionados.")
else:
    cols_por_fila = 3
    for i in range(0, len(chats_filtrados), cols_por_fila):
        fila = st.columns(cols_por_fila)
        for j, chat in enumerate(chats_filtrados[i : i + cols_por_fila]):
            with fila[j]:
                with st.container(border=True):
                    tiempo_info = calcular_tiempo_relativo_ui(
                        chat.get("ultimo_mensaje_cliente_at")
                    )
                    st.caption(
                        f"{tiempo_info['color']} {tiempo_info['texto']} | 📱 {str(chat.get('chat_id','')).replace('@c.us', '')}"
                    )

                    st.subheader(f"💬 {chat.get('nombre', 'Cliente')}")

                    srv = chat.get("servicio", "Cotización Courier")
                    tipo_c = chat.get("tipo_contacto", "🌱 Prospecto Nuevo")
                    st.markdown(f"`{srv}` | `{tipo_c}`")

                    cot = (
                        f"${chat['cotizacion_total']:,.2f} USD"
                        if chat.get("cotizacion_total")
                        else "Pendiente"
                    )
                    st.write(f"💰 **Cotización:** {cot}")
                    st.write(f"👨‍💼 **Asesor:** {chat.get('asesor_asignado')}")

                    bot_estado_icon = (
                        "🤖 Bot Activo"
                        if chat.get("bot_activo", 1) == 1
                        else "🤫 En manos de Asesor"
                    )
                    st.caption(bot_estado_icon)

                    paso = chat.get("paso_happy_path", 1)
                    circulitos = "".join(
                        [
                            (
                                "🟢 "
                                if p < paso
                                else "🟡 " if p == paso else "⚪ "
                            )
                            for p in range(1, 6)
                        ]
                    )
                    st.markdown(f"**Avance:** {circulitos}")

                    if st.button("Abrir Chat ➡️", key=f"btn_{chat['chat_id']}"):
                        st.session_state.chat_seleccionado = chat["chat_id"]
                        st.rerun()

# ----------------- 6. CONVERSACIÓN ABIERTA Y ACCIONES -----------------
if (
    "chat_seleccionado" in st.session_state
    and st.session_state.chat_seleccionado
):
    sel_id = st.session_state.chat_seleccionado
    info_chat = next(
        (c for c in chats if str(c.get("chat_id")) == str(sel_id)), None
    )

    if info_chat:
        st.markdown("---")
        st.header(
            f"Conversación: {info_chat.get('nombre')} ({str(sel_id).replace('@c.us', '')})"
        )

        c_act1, c_act2, c_act3 = st.columns([3, 2, 2])

        # Control de Estado
        with c_act1:
            nuevo_est = st.selectbox(
                "Estado del Lead:",
                ["Atendido por Bot", "Listo para Asesor", "Cerrado"],
                index=["Atendido por Bot", "Listo para Asesor", "Cerrado"].index(
                    info_chat.get("estado", "Atendido por Bot")
                ),
            )
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("💾 Guardar Estado"):
                    activo = 1 if nuevo_est == "Atendido por Bot" else 0
                    httpx.post(
                        f"{BACKEND_URL}/api/update-chat-status",
                        json={
                            "chat_id": sel_id,
                            "nuevo_estado": nuevo_est,
                            "bot_activo": activo,
                        },
                    )
                    st.success("Estado guardado")
                    st.rerun()

            with col_b2:
                bot_actualmente_activo = bool(info_chat.get("bot_activo", 1))
                if bot_actualmente_activo:
                    if st.button("🤫 Silenciar Bot"):
                        httpx.post(
                            f"{BACKEND_URL}/api/update-chat-status",
                            json={
                                "chat_id": sel_id,
                                "nuevo_estado": info_chat.get("estado"),
                                "bot_activo": 0,
                            },
                        )
                        st.rerun()
                else:
                    if st.button("🤖 Reactivar Bot", type="primary"):
                        httpx.post(
                            f"{BACKEND_URL}/api/update-chat-status",
                            json={
                                "chat_id": sel_id,
                                "nuevo_estado": "Atendido por Bot",
                                "bot_activo": 1,
                            },
                        )
                        st.rerun()

        with c_act2:
            st.write(f"Tipo: **{info_chat.get('tipo_contacto')}**")
            st.write(f"Estado: **{info_chat.get('estado')}**")

        # Recordatorio y Descarga de PDF
        with c_act3:
            st.write("Acciones:")
            if st.button("⚡ Enviar Recordatorio"):
                cot = info_chat.get("cotizacion_total")
                monto_txt = f"de ${cot:,.2f} USD" if cot else ""
                nudge_msg = (
                    f"¡Hola {info_chat.get('nombre')}! 👋 Te escribo de Globex para recordarte que tu cotización {monto_txt} "
                    f"sigue activa en nuestro sistema.\n\n"
                    f"¿Deseas que te asigne tu casillero en Miami para proceder con tu compra?"
                )
                try:
                    res = httpx.post(
                        f"{BACKEND_URL}/api/send-advisor-message",
                        json={
                            "chat_id": sel_id,
                            "nombre_asesor": usuario["nombre"],
                            "texto": nudge_msg,
                        },
                        timeout=10.0,
                    )
                    if res.status_code == 200:
                        st.success("Recordatorio enviado")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

            # Botón de Descarga directa del PDF desde Render
            if info_chat.get("cotizacion_total"):
                pdf_url = f"{BACKEND_URL}/api/download-pdf/{sel_id}"
                try:
                    pdf_res = httpx.get(pdf_url, timeout=10.0)
                    if pdf_res.status_code == 200:
                        st.download_button(
                            label="📄 Descargar Proforma PDF",
                            data=pdf_res.content,
                            file_name=f"Proforma_Globex_{sel_id}.pdf",
                            mime="application/pdf",
                        )
                except Exception:
                    pass

        # Chat en vivo
        renderizar_mensajes_vivos(sel_id)

        # Envío de Mensaje de texto a WhatsApp
        respuesta_asesor = st.text_input(
            "Escribe tu respuesta como Asesor:", key=f"input_{sel_id}"
        )
        if st.button("📤 Enviar Mensaje a WhatsApp"):
            if respuesta_asesor.strip():
                try:
                    res = httpx.post(
                        f"{BACKEND_URL}/api/send-advisor-message",
                        json={
                            "chat_id": sel_id,
                            "nombre_asesor": usuario["nombre"],
                            "texto": respuesta_asesor.strip().strip('"'),
                        },
                        timeout=10.0,
                    )
                    if res.status_code == 200:
                        st.success("Mensaje enviado con éxito vía Meta")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error al enviar: {e}")