import os
from database import (
    actualizar_estado_chat,
    alternar_tipo_cliente,
    calcular_tiempo_relativo,
    init_db,
    obtener_mensajes_chat,
    obtener_todos_los_chats,
    registrar_mensaje_saliente,
)
from dotenv import load_dotenv
import httpx
import streamlit as st

load_dotenv()
init_db()

st.set_page_config(
    page_title="Globex | Panel de Asesores Pro",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

def enviar_archivo_a_whatsapp(
    chat_id: str,
    file_bytes: bytes,
    nombre_archivo: str,
    caption: str = "📄 Adjunto tu Proforma Oficial de Globex Courier",
) -> bool:
    """Sube y envía un archivo PDF real al WhatsApp del cliente usando la Graph API oficial de Meta."""
    META_PHONE_ID = os.getenv("META_PHONE_NUMBER_ID")
    META_TOKEN = os.getenv("META_ACCESS_TOKEN")

    if not META_PHONE_ID or not META_TOKEN:
        st.error(
            "Faltan credenciales de Meta (META_PHONE_NUMBER_ID o META_ACCESS_TOKEN) en el archivo .env"
        )
        return False

    clean_phone = chat_id.replace("@c.us", "").strip()

    try:
        with httpx.Client(timeout=30.0) as client:
            # 1. SUBIR EL ARCHIVO A META (/media)
            upload_url = (
                f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/media"
            )
            headers_upload = {"Authorization": f"Bearer {META_TOKEN}"}
            files = {"file": (nombre_archivo, file_bytes, "application/pdf")}
            data_upload = {
                "messaging_product": "whatsapp",
                "type": "application/pdf",
            }

            upload_res = client.post(
                upload_url,
                headers=headers_upload,
                data=data_upload,
                files=files,
            )

            if upload_res.status_code != 200:
                st.error(
                    f"Error de Meta al subir archivo ({upload_res.status_code}): {upload_res.text}"
                )
                return False

            media_id = upload_res.json().get("id")

            # 2. ENVIAR EL MENSAJE CON EL ARCHIVO ADJUNTO AL CLIENTE
            messages_url = (
                f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/messages"
            )
            headers_message = {
                "Authorization": f"Bearer {META_TOKEN}",
                "Content-Type": "application/json",
            }
            payload_message = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_phone,
                "type": "document",
                "document": {
                    "id": media_id,
                    "caption": caption,
                    "filename": nombre_archivo,
                },
            }

            send_res = client.post(
                messages_url, headers=headers_message, json=payload_message
            )

            if send_res.status_code == 200:
                return True
            else:
                st.error(
                    f"Error de Meta al entregar documento ({send_res.status_code}): {send_res.text}"
                )
                return False

    except Exception as e:
        st.error(f"Error de conexión con Meta Cloud API: {e}")
        return False
    
# ----------------- 1. LOGIN DE ASESORES -----------------
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
            usuario_input = (
                st.text_input("Usuario:").strip().lower()
            )
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
    chats = obtener_todos_los_chats()
    st.metric("Total Chats", len(chats))
    listos = sum(1 for c in chats if c["estado"] == "Listo para Asesor")
    st.metric("Requieren Asesor 🎯", listos)

    st.markdown("---")
    auto_refresh = st.checkbox("⚡ Auto-actualizar mensajes", value=True)


# ----------------- 3. REPRODUCTOR DE MENSAJES EN TIEMPO REAL -----------------
@st.fragment(run_every=3.0 if auto_refresh else None)
def renderizar_mensajes_vivos(chat_id_seleccionado: str):
    """Actualiza automáticamente la conversación cada 3 segundos."""
    mensajes = obtener_mensajes_chat(chat_id_seleccionado)
    chat_box = st.container(height=350)
    with chat_box:
        for m in mensajes:
            if m["emisor"] == "cliente":
                with st.chat_message("user"):
                    st.write(m["texto"])
            elif m["emisor"] == "bot":
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

# Filtrado de tarjetas
chats_filtrados = chats
if filtro_estado != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c["estado"] == filtro_estado
    ]
if filtro_asesor != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c["asesor_asignado"] == filtro_asesor
    ]
if filtro_servicio != "Todos":
    chats_filtrados = [
        c for c in chats_filtrados if c.get("servicio") == filtro_servicio
    ]

st.markdown("---")

# ----------------- 5. CUADRÍCULA DE TARJETAS (EXCALIDRAW) -----------------
if not chats_filtrados:
    st.info("No hay chats con los filtros seleccionados.")
else:
    cols_por_fila = 3
    for i in range(0, len(chats_filtrados), cols_por_fila):
        fila = st.columns(cols_por_fila)
        for j, chat in enumerate(chats_filtrados[i : i + cols_por_fila]):
            with fila[j]:
                with st.container(border=True):
                    # Semáforo de tiempo transcurrido
                    tiempo_info = calcular_tiempo_relativo(
                        chat.get("ultimo_mensaje_cliente_at")
                    )
                    st.caption(
                        f"{tiempo_info['color']} {tiempo_info['texto']} | 📱 {chat['chat_id'].replace('@c.us', '')}"
                    )

                    st.subheader(f"💬 {chat['nombre']}")

                    # Badges de Servicio y Tipo de Contacto
                    srv = chat.get("servicio", "Cotización Courier")
                    tipo_c = chat.get("tipo_contacto", "🌱 Prospecto Nuevo")
                    st.markdown(f"`{srv}` | `{tipo_c}`")

                    cot = (
                        f"${chat['cotizacion_total']:,.2f} USD"
                        if chat["cotizacion_total"]
                        else "Pendiente"
                    )
                    st.write(f"💰 **Cotización:** {cot}")
                    st.write(f"👨‍💼 **Asesor:** {chat['asesor_asignado']}")

                    # Estado de bot
                    bot_estado_icon = (
                        "🤖 Bot Activo"
                        if chat.get("bot_activo", 1) == 1
                        else "🤫 En manos de Asesor"
                    )
                    st.caption(bot_estado_icon)

                    # Circulitos del Happy Path
                    paso = chat["paso_happy_path"]
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
    info_chat = next((c for c in chats if c["chat_id"] == sel_id), None)

    if info_chat:
        st.markdown("---")
        st.header(
            f"Conversación: {info_chat['nombre']} ({sel_id.replace('@c.us', '')})"
        )

        c_act1, c_act2, c_act3 = st.columns([3, 2, 2])

        # Control de Estado y Silenciado del Bot
        with c_act1:
            nuevo_est = st.selectbox(
                "Estado del Lead:",
                ["Atendido por Bot", "Listo para Asesor", "Cerrado"],
                index=["Atendido por Bot", "Listo para Asesor", "Cerrado"].index(
                    info_chat["estado"]
                ),
            )
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("💾 Guardar Estado"):
                    activo = 1 if nuevo_est == "Atendido por Bot" else 0
                    actualizar_estado_chat(
                        sel_id, nuevo_est, bot_activo=activo
                    )
                    st.success("Estado guardado")
                    st.rerun()

            with col_b2:
                bot_actualmente_activo = bool(info_chat.get("bot_activo", 1))
                if bot_actualmente_activo:
                    if st.button("🤫 Silenciar Bot"):
                        actualizar_estado_chat(
                            sel_id, info_chat["estado"], bot_activo=0
                        )
                        st.warning("Bot silenciado.")
                        st.rerun()
                else:
                    if st.button("🤖 Reactivar Bot", type="primary"):
                        actualizar_estado_chat(
                            sel_id, "Atendido por Bot", bot_activo=1
                        )
                        st.success("¡Bot reactivado!")
                        st.rerun()

        # Tipo de Contacto
        with c_act2:
            st.write(
                f"Tipo actual: **{info_chat.get('tipo_contacto', 'Prospecto')}**"
            )
            if st.button("🔄 Cambiar Prospecto / Cliente"):
                alternar_tipo_cliente(sel_id)
                st.success("Cambiado")
                st.rerun()

        # Acciones Comerciales y Recuperador de Leads (Versión Meta Cloud API)
        with c_act3:
            st.write("Recuperador de Leads:")
            if st.button("⚡ Enviar Recordatorio"):
                cot = info_chat.get("cotizacion_total")
                monto_txt = f"de ${cot:,.2f} USD" if cot else ""
                nudge_msg = (
                    f"¡Hola {info_chat['nombre']}! 👋 Te escribo de Globex para recordarte que tu cotización {monto_txt} "
                    f"sigue guardada en nuestro sistema.\n\n"
                    f"¿Deseas que te asigne tu casillero oficial en Miami para proceder con tu compra?"
                )

                META_PHONE_ID = os.getenv("META_PHONE_NUMBER_ID")
                META_TOKEN = os.getenv("META_ACCESS_TOKEN")
                clean_phone = sel_id.replace("@c.us", "").strip()

                url = f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/messages"
                headers = {
                    "Authorization": f"Bearer {META_TOKEN}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_phone,
                    "type": "text",
                    "text": {"preview_url": False, "body": nudge_msg},
                }

                try:
                    res = httpx.post(
                        url, json=payload, headers=headers, timeout=10.0
                    )
                    if res.status_code == 200:
                        registrar_mensaje_saliente(
                            sel_id, usuario["nombre"], nudge_msg
                        )
                        st.success("¡Recordatorio enviado vía Meta Cloud API!")
                        st.rerun()
                    else:
                        st.error(
                            f"Error de Meta ({res.status_code}): {res.text}"
                        )
                except Exception as e:
                    st.error(f"Error de conexión con Meta: {e}")

        # 📄 BOTÓN DE DESCARGA DE LA PROFORMA OFICIAL EN PDF (SI EXISTE)
        if info_chat.get("cotizacion_total"):
            numero_limpio = sel_id.replace("@c.us", "")
            carpeta_pdf = "cotizaciones_pdf"
            if os.path.exists(carpeta_pdf):
                archivos_pdf = [
                    f
                    for f in os.listdir(carpeta_pdf)
                    if f.startswith(f"Proforma_Globex_{numero_limpio}")
                ]
                if archivos_pdf:
                    archivos_pdf.sort(reverse=True)
                    ruta_pdf = os.path.join(carpeta_pdf, archivos_pdf[0])
                    with open(ruta_pdf, "rb") as f_pdf:
                        st.download_button(
                            label="📄 Descargar Proforma Oficial en PDF",
                            data=f_pdf,
                            file_name=archivos_pdf[0],
                            mime="application/pdf",
                        )

        # Chat en vivo
        renderizar_mensajes_vivos(sel_id)

        # ─────────────────────────────────────────────────────────────
        # 1. CAJA PARA ENVIAR TEXTO A WHATSAPP
        # ─────────────────────────────────────────────────────────────
        respuesta_asesor = st.text_input(
            "Escribe tu respuesta como Asesor para enviar a WhatsApp:",
            key=f"input_{sel_id}",
        )
        # EN dashboard.py (ENVÍO VÍA META CLOUD API):
        if st.button("📤 Enviar Mensaje a WhatsApp"):
            if respuesta_asesor.strip():
                META_PHONE_ID = os.getenv("META_PHONE_NUMBER_ID")
                META_TOKEN = os.getenv("META_ACCESS_TOKEN")
                url = f"https://graph.facebook.com/v21.0/{META_PHONE_ID}/messages"
                headers = {
                    "Authorization": f"Bearer {META_TOKEN}",
                    "Content-Type": "application/json",
                }
                mensaje_limpio = respuesta_asesor.strip().strip('"')
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": sel_id.replace("@c.us", ""),
                    "type": "text",
                    "text": {"preview_url": False, "body": mensaje_limpio},
                }

                try:
                    res = httpx.post(
                        url, json=payload, headers=headers, timeout=10.0
                    )
                    if res.status_code == 200:
                        registrar_mensaje_saliente(
                            sel_id, usuario["nombre"], mensaje_limpio
                        )
                        actualizar_estado_chat(
                            sel_id, "Listo para Asesor", bot_activo=0
                        )
                        st.success("Mensaje entregado vía Meta Cloud API")
                        st.rerun()
                    else:
                        st.error(f"Error Meta API ({res.status_code}): {res.text}")
                except Exception as e:
                    st.error(f"Error de conexión con Meta: {e}")

        st.markdown("---")

        # ─────────────────────────────────────────────────────────────
        # 2. SECCIÓN PARA ENVIAR PROFORMA / DOCUMENTO PDF A WHATSAPP (AQUÍ VA)
        # ─────────────────────────────────────────────────────────────
        with st.expander("📎 Enviar Proforma o Documento PDF a WhatsApp"):
            col_pdf1, col_pdf2 = st.columns(2)

            # OPCIÓN A: Enviar la proforma ya calculada automáticamente
            with col_pdf1:
                st.markdown("**1. Proforma Generada del Sistema:**")
                numero_limpio = sel_id.replace("@c.us", "")
                carpeta_pdf = "cotizaciones_pdf"
                pdfs = (
                    [
                        f
                        for f in os.listdir(carpeta_pdf)
                        if f.startswith(f"Proforma_Globex_{numero_limpio}")
                    ]
                    if os.path.exists(carpeta_pdf)
                    else []
                )

                if pdfs:
                    pdfs.sort(reverse=True)
                    ultimo_pdf = pdfs[0]
                    ruta_pdf = os.path.join(carpeta_pdf, ultimo_pdf)
                    st.caption(f"Archivo listo: `{ultimo_pdf}`")

                    if st.button("🚀 Enviar Proforma Oficial a WhatsApp"):
                        with open(ruta_pdf, "rb") as f:
                            contenido_bytes = f.read()
                        if enviar_archivo_a_whatsapp(
                            sel_id,
                            contenido_bytes,
                            ultimo_pdf,
                            caption="📄 Hola, te adjunto tu Proforma Oficial de Globex con el desglose de flete e impuestos.",
                        ):
                            registrar_mensaje_saliente(
                                sel_id,
                                usuario["nombre"],
                                f"[📄 PDF ENVIADO: {ultimo_pdf}]",
                            )
                            st.success("¡Proforma PDF entregada a WhatsApp!")
                            st.rerun()
                else:
                    st.info("No hay proforma generada aún para este chat.")

            # OPCIÓN B: Subir y enviar cualquier otro archivo manual
            with col_pdf2:
                st.markdown("**2. Subir otro PDF desde tu equipo:**")
                archivo_subido = st.file_uploader(
                    "Carga un PDF:", type=["pdf"], key=f"upload_{sel_id}"
                )
                caption_personalizado = st.text_input(
                    "Mensaje opcional adjunto:",
                    value="📄 Adjunto documento de Globex",
                    key=f"caption_{sel_id}",
                )

                if archivo_subido is not None:
                    if st.button("📤 Enviar PDF Subido a WhatsApp"):
                        bytes_subidos = archivo_subido.read()
                        if enviar_archivo_a_whatsapp(
                            sel_id,
                            bytes_subidos,
                            archivo_subido.name,
                            caption=caption_personalizado,
                        ):
                            registrar_mensaje_saliente(
                                sel_id,
                                usuario["nombre"],
                                f"[📄 PDF MANUAL: {archivo_subido.name}]",
                            )
                            st.success(
                                "¡Documento PDF subido y entregado a WhatsApp!"
                            )
                            st.rerun()