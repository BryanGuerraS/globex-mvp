"""Consola de asesores de Globex (Streamlit).

Diseño según las guías oficiales de Streamlit (skill developing-with-streamlit):
tema en .streamlit/config.toml (sin CSS), íconos Material en vez de emojis,
badges para estados, filtros en la barra lateral y navegación superior.

La bandeja sigue el patrón lista + conversación + detalle de las consolas de
atención (Intercom, HubSpot): a la izquierda los chats con su tiempo de espera,
al centro la conversación y a la derecha los datos del lead y las acciones.
"""

from datetime import datetime
import os
import re
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# Hora de Perú en todo el sistema: Render y Streamlit Cloud corren en UTC.
ZONA_HORARIA = ZoneInfo("America/Lima")


def ahora() -> datetime:
    """Fecha y hora actual de Lima (sin zona, como se guarda en SQLite)."""
    return datetime.now(ZONA_HORARIA).replace(tzinfo=None)

from dotenv import load_dotenv
import httpx
import pandas as pd
import streamlit as st

from metricas import CATEGORIAS_ERROR, REVISION_CORREGIDA, REVISION_ERROR, REVISION_VALIDADA

load_dotenv()

# URL base del backend en Render y key compartida (Streamlit Cloud: Secrets)
BACKEND_URL = os.getenv("BACKEND_URL", "https://globex-mvp.onrender.com")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
COLOR_MARCA = "#2E1A47"  # morado del logo de Globex

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO = os.path.join(ASSETS, "logo_globex.png")
LOGO_OSCURO = os.path.join(ASSETS, "logo_globex_oscuro.png")  # texto blanco para tema oscuro
ICONO = os.path.join(ASSETS, "logo_icono.png")
LOGO_H = os.path.join(ASSETS, "logo_horizontal.png")  # barra lateral (st.logo limita la altura)
LOGO_H_OSCURO = os.path.join(ASSETS, "logo_horizontal_oscuro.png")

st.set_page_config(
    page_title="Globex · Consola de asesores",
    page_icon=ICONO,
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def _cliente_api() -> httpx.Client:
    return httpx.Client(headers={"X-API-Key": DASHBOARD_API_KEY}, timeout=10.0)


api = _cliente_api()

# Entorno de prueba: credenciales fijas a propósito (ver CLAUDE.md)
USUARIOS = {
    "admin": {"nombre": "Admin", "password": "123", "rol": "admin"},
    "bryan": {"nombre": "Bryan", "password": "123", "rol": "asesor"},
    "juan": {"nombre": "Juan", "password": "123", "rol": "asesor"},
    "anyela": {"nombre": "Anyela", "password": "123", "rol": "asesor"},
}
ASESORES = [u["nombre"] for u in USUARIOS.values() if u["rol"] == "asesor"]
SIN_ASIGNAR = "Sin asignar"

# Nombres profesionales del tipo de contacto (incluye los valores antiguos con emoji)
TIPOS_CONTACTO = {"🌱 Prospecto Nuevo": "Nuevo prospecto", "⭐ Cliente Frecuente": "Cliente recurrente"}

ESTADOS = {
    "Atendido por Bot": {"corto": "Globix", "color": "blue", "icono": ":material/smart_toy:"},
    "Listo para Asesor": {"corto": "Requiere asesor", "color": "orange", "icono": ":material/support_agent:"},
    "Cerrado": {"corto": "Cerrado", "color": "gray", "icono": ":material/check_circle:"},
}
PASOS_HAPPY_PATH = ["Contacto", "Consulta", "Cotización", "Derivación", "Cierre"]

st.session_state.setdefault("autenticado", False)
st.session_state.setdefault("usuario_actual", None)
st.session_state.setdefault("chat_seleccionado", None)


# ---------------------------------------------------------------- API

def fetch_chats() -> List[Dict]:
    try:
        r = api.get(f"{BACKEND_URL}/api/chats")
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def fetch_messages(chat_id: str) -> List[Dict]:
    try:
        r = api.get(f"{BACKEND_URL}/api/messages/{chat_id}")
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def fetch_metricas(horas: float) -> Dict:
    try:
        r = api.get(f"{BACKEND_URL}/api/metricas", params={"horas": horas, "ultimos": 50})
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def actualizar_estado(chat_id: str, estado: str) -> bool:
    """El bot responde solo cuando el chat está 'Atendido por Bot'."""
    try:
        r = api.post(
            f"{BACKEND_URL}/api/update-chat-status",
            json={"chat_id": chat_id, "nuevo_estado": estado, "bot_activo": 1 if estado == "Atendido por Bot" else 0},
        )
        return r.status_code == 200
    except Exception:
        return False


def enviar_mensaje(chat_id: str, texto: str) -> bool:
    try:
        r = api.post(
            f"{BACKEND_URL}/api/send-advisor-message",
            json={"chat_id": chat_id, "nombre_asesor": st.session_state.usuario_actual["nombre"], "texto": texto},
        )
        return r.status_code == 200
    except Exception:
        return False


def fetch_revisiones(chat_id: str) -> List[Dict]:
    try:
        r = api.get(f"{BACKEND_URL}/api/revisiones/{chat_id}")
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def enviar_proforma_pdf(chat_id: str) -> bool:
    """Valida la cotización de Globix y envía el PDF formal al cliente por WhatsApp."""
    try:
        r = api.post(
            f"{BACKEND_URL}/api/send-pdf",
            json={"chat_id": chat_id, "nombre_asesor": st.session_state.usuario_actual["nombre"]},
            timeout=40,
        )
        return r.status_code == 200
    except Exception:
        return False


def registrar_revision(chat_id: str, tipo: str, categoria: str, nota: str, mensaje_id: Optional[int] = None) -> bool:
    try:
        r = api.post(
            f"{BACKEND_URL}/api/revision",
            json={"chat_id": chat_id, "nombre_asesor": st.session_state.usuario_actual["nombre"], "tipo": tipo,
                  "categoria": categoria, "nota": nota, "mensaje_id": mensaje_id},
        )
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------- Formato

def nombre_mostrado(chat: Dict) -> str:
    """Nombre que dio el cliente; si aún no lo dio, el de su perfil de WhatsApp."""
    return chat.get("nombre_cliente") or chat.get("nombre") or "Cliente"


def _fecha(valor) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor).split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def minutos_desde(valor) -> Optional[int]:
    dt = _fecha(valor)
    return None if dt is None else max(0, int((ahora() - dt).total_seconds() // 60))


def texto_espera(minutos: Optional[int]) -> str:
    if minutos is None:
        return "Sin actividad"
    if minutos < 1:
        return "Ahora"
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 1440:
        return f"{minutos // 60} h"
    return f"{minutos // 1440} d"


def color_espera(minutos: Optional[int]) -> str:
    """Semáforo de tiempo desde el último mensaje del cliente."""
    if minutos is None:
        return "gray"
    return "green" if minutos < 15 else "orange" if minutos <= 45 else "red"


def badge_estado(estado: str) -> str:
    e = ESTADOS.get(estado, {"corto": estado or "—", "color": "gray"})
    return f":{e['color']}-badge[{e['corto']}]"


def badge_globix(chat: Dict) -> str:
    """Punto verde: Globix responde en este chat. Punto gris: Globix pausado."""
    color = "green" if chat.get("bot_activo", 1) else "gray"
    return f":{color}-badge[:material/fiber_manual_record: Globix]"


def badges_chat(chat: Dict) -> str:
    """Globix (activo/pausado) + estado del lead si no lo atiende el bot."""
    badges = [badge_globix(chat)]
    if chat.get("estado") != "Atendido por Bot":
        badges.append(badge_estado(chat.get("estado")))
    return " ".join(badges)


def tipo_contacto(chat: Dict) -> str:
    valor = chat.get("tipo_contacto") or "Nuevo prospecto"
    return TIPOS_CONTACTO.get(valor, valor)


def badge_espera(minutos: Optional[int]) -> str:
    return f":{color_espera(minutos)}-badge[:material/schedule: {texto_espera(minutos)}]"


def usd(valor) -> str:
    return f"USD {valor:,.2f}" if valor else "—"


_OPCIONES = re.compile(r"\n\[Opciones: (.+)\]\s*$")
_NEGRITA_WA = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_TACHADO_WA = re.compile(r"(?<![\w~])~(?!\s)([^~\n]+?)(?<!\s)~(?![\w~])")


def whatsapp_a_markdown(texto: str) -> str:
    """Muestra el mensaje como se ve en WhatsApp.

    - '$' se escapa: Markdown de Streamlit lo trata como fórmula LaTeX.
    - *negrita* y ~tachado~ de WhatsApp pasan a **negrita** y ~~tachado~~.
    - Cada salto de línea se conserva (en Markdown uno solo no corta la línea).
    """
    texto = (texto or "").replace("$", "\\$")
    texto = _NEGRITA_WA.sub(r"**\1**", texto)
    texto = _TACHADO_WA.sub(r"~~\1~~", texto)
    return texto.replace("\n", "  \n")


def separar_opciones(texto: str):
    """Los mensajes con botones se guardan como 'cuerpo\\n[Opciones: a | b]'."""
    m = _OPCIONES.search(texto or "")
    if not m:
        return texto, []
    return texto[: m.start()], [o.strip() for o in m.group(1).split("|")]


# ---------------------------------------------------------------- Páginas

def _tema_oscuro() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def logo_segun_tema(horizontal: bool = False) -> str:
    if horizontal:
        return LOGO_H_OSCURO if _tema_oscuro() else LOGO_H
    return LOGO_OSCURO if _tema_oscuro() else LOGO


def pagina_login():
    st.space("large")
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        with st.container(horizontal_alignment="center"):
            st.image(logo_segun_tema(), width=180)
            st.caption("Consola de asesores comerciales", text_alignment="center")
        with st.form("login", border=True):
            usuario = st.text_input("Usuario", placeholder="bryan").strip().lower()
            password = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar", type="primary", width="stretch", icon=":material/login:"):
                if usuario in USUARIOS and USUARIOS[usuario]["password"] == password:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = USUARIOS[usuario]
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.", icon=":material/error:")
        st.caption("Entorno de pruebas · Capstone UTEC", text_alignment="center")


def barra_lateral() -> Dict:
    """Usuario, filtros globales y actualización automática."""
    usuario = st.session_state.usuario_actual
    with st.sidebar:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{usuario['nombre']}**")
            st.badge("Admin" if usuario["rol"] == "admin" else "Asesor",
                     color="violet" if usuario["rol"] == "admin" else "gray")
        if st.button("Cerrar sesión", icon=":material/logout:", type="tertiary"):
            st.session_state.autenticado = False
            st.session_state.usuario_actual = None
            st.session_state.chat_seleccionado = None
            st.rerun()

        st.subheader("Filtros", icon=":material/filter_list:")
        busqueda = st.text_input("Buscar", placeholder="Nombre o ID", icon=":material/search:")
        estado = st.segmented_control(
            "Estado", ["Todos", "Requiere asesor", "Globix", "Cerrado"], default="Todos", required=True
        )
        asesor = st.selectbox("Asesor", ["Todos", SIN_ASIGNAR] + ASESORES)
        servicio = st.selectbox(
            "Servicio",
            ["Todos", "Cotización Courier", "Cotización Courier (alto valor)", "Seguimiento Courier",
             "Cotización Viajero", "Restringido (DIGEMID)", "Mercancía Prohibida"],
        )
        st.space("small")
        auto = st.toggle("Actualizar automáticamente", value=True, help="Mensajes del chat abierto cada 5 s; bandeja, KPIs y detalle cada 15 s.")
        st.caption(f"Backend: {BACKEND_URL.replace('https://', '')}")
    return {"busqueda": busqueda, "estado": estado, "asesor": asesor, "servicio": servicio, "auto": auto}


def filtrar(chats: List[Dict], f: Dict) -> List[Dict]:
    estado_por_corto = {v["corto"]: k for k, v in ESTADOS.items()}
    res = chats
    if f["estado"] != "Todos":
        res = [c for c in res if c.get("estado") == estado_por_corto[f["estado"]]]
    if f["asesor"] == SIN_ASIGNAR:
        res = [c for c in res if not c.get("asesor_asignado")]
    elif f["asesor"] != "Todos":
        res = [c for c in res if c.get("asesor_asignado") == f["asesor"]]
    if f["servicio"] != "Todos":
        res = [c for c in res if c.get("servicio") == f["servicio"]]
    q = f["busqueda"].strip().lower()
    if q:
        res = [c for c in res if q in nombre_mostrado(c).lower() or q in str(c.get("chat_id", "")).lower()]
    # Primero los que requieren asesor y llevan más tiempo esperando
    return sorted(
        res,
        key=lambda c: (c.get("estado") != "Listo para Asesor", -(minutos_desde(c.get("ultimo_mensaje_cliente_at")) or 0)),
    )


def fila_kpis(chats: List[Dict]):
    requieren = [c for c in chats if c.get("estado") == "Listo para Asesor"]
    demorados = [c for c in requieren if (minutos_desde(c.get("ultimo_mensaje_cliente_at")) or 0) > 45]
    cotizado = sum(c.get("cotizacion_total") or 0 for c in chats)
    con_cotizacion = sum(1 for c in chats if c.get("cotizacion_total"))
    with st.container(horizontal=True):
        st.metric("Conversaciones", len(chats), border=True, icon=":material/forum:")
        st.metric("Requieren asesor", len(requieren), border=True, icon=":material/support_agent:")
        st.metric("Esperan más de 45 min", len(demorados), border=True, icon=":material/schedule:",
                  help="Chats derivados cuyo último mensaje del cliente tiene más de 45 minutos.")
        st.metric("Cotizado", usd(cotizado), border=True, icon=":material/request_quote:",
                  help=f"Suma de las cotizaciones emitidas ({con_cotizacion} chats).")


def lista_chats(chats: List[Dict]):
    st.markdown(f"**Bandeja** · {len(chats)}")
    with st.container(height=640, border=False, gap="small"):
        if not chats:
            st.caption("No hay conversaciones con estos filtros.")
        for chat in chats:
            seleccionado = chat["chat_id"] == st.session_state.chat_seleccionado
            minutos = minutos_desde(chat.get("ultimo_mensaje_cliente_at"))
            with st.container(border=True, gap="xsmall"):
                if st.button(
                    nombre_mostrado(chat),
                    key=f"abrir_{chat['chat_id']}",
                    type="primary" if seleccionado else "tertiary",
                    icon=":material/chat:" if seleccionado else ":material/chat_bubble_outline:",
                    width="stretch",
                ):
                    st.session_state.chat_seleccionado = chat["chat_id"]
                    st.rerun(scope="app")
                st.markdown(f"{badges_chat(chat)} {badge_espera(minutos)}")
                st.caption(f"{chat.get('servicio') or '—'} · {usd(chat.get('cotizacion_total'))}")


def burbuja(m: Dict, nombre_cliente: str):
    emisor = m.get("emisor") or ""
    hora = _fecha(m.get("timestamp"))
    hora_txt = hora.strftime("%H:%M") if hora else ""
    cuerpo, opciones = separar_opciones(m.get("texto") or "")
    if emisor == "cliente":
        rol, avatar, autor = "user", ":material/person:", nombre_cliente
    elif emisor.lower().startswith("bot"):
        rol, avatar, autor = "assistant", ":material/smart_toy:", "Globix"
        if "recordatorio" in emisor:
            autor += " · recordatorio automático"
    else:
        rol, avatar, autor = "assistant", ":material/support_agent:", emisor
    with st.chat_message(rol, avatar=avatar):
        st.caption(f"**{autor}** · {hora_txt}")
        st.markdown(whatsapp_a_markdown(cuerpo))
        if opciones:
            st.markdown(" ".join(f":gray-badge[{o}]" for o in opciones))


def panel_conversacion(chat: Dict, auto: bool):
    nombre = nombre_mostrado(chat)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader(nombre)
        st.markdown(badges_chat(chat))
    st.caption(f"ID {chat['chat_id']}")

    @st.fragment(run_every=5 if auto else None)
    def mensajes():
        with st.container(height=480, border=True):
            msgs = fetch_messages(chat["chat_id"])
            if not msgs:
                st.caption("Sin mensajes todavía.")
            for m in msgs:
                burbuja(m, nombre)

    mensajes()

    bot_activo = bool(chat.get("bot_activo", 1))
    if bot_activo:
        st.caption(":material/smart_toy: Globix está respondiendo. Si escribes, el chat pasa a tu cargo y el bot se pausa.")
    respuesta = st.chat_input(f"Responder a {nombre.split()[0]} por WhatsApp…", key=f"input_{chat['chat_id']}")
    if respuesta and respuesta.strip():
        if enviar_mensaje(chat["chat_id"], respuesta.strip()):
            st.toast("Mensaje enviado por WhatsApp", icon=":material/check_circle:")
        else:
            st.toast("No se pudo enviar el mensaje", icon=":material/error:")
        st.rerun(scope="app")


def _asignar_asesor(chat_id: str, estado: str, clave: str):
    """Callback del selector de asesor: solo corre cuando el usuario elige uno."""
    asesor = st.session_state[clave]
    if not asesor or asesor == st.session_state.get(f"{clave}_backend"):
        return
    try:
        r = api.post(
            f"{BACKEND_URL}/api/update-chat-status",
            json={"chat_id": chat_id, "nuevo_estado": estado or "Atendido por Bot", "nuevo_asesor": asesor},
        )
        ok = r.status_code == 200
    except Exception:
        ok = False
    if ok:
        st.session_state[f"{clave}_backend"] = asesor
        st.toast(f"Asignado a {asesor}", icon=":material/check_circle:")
    else:
        st.toast("No se pudo asignar el asesor", icon=":material/error:")


def _cambiar_estado(chat_id: str, clave: str):
    """Callback del selector de estado: solo corre cuando el asesor hace clic."""
    nuevo = st.session_state[clave]
    if nuevo == st.session_state.get(f"{clave}_backend"):
        return  # solo se sincronizó con el backend; no es un cambio del asesor
    if actualizar_estado(chat_id, nuevo):
        st.session_state[f"{clave}_backend"] = nuevo
        st.toast(f"Estado: {ESTADOS[nuevo]['corto']}", icon=":material/check_circle:")
    else:
        st.toast("No se pudo cambiar el estado", icon=":material/error:")


MOTIVOS_CORTOS = {
    "asesor": "Pidió asesor",
    "tope": "Compra de más de USD 1,200",
    "seguimiento": "Seguimiento de paquete",
    "viajero": "Modalidad viajero",
    "restringido": "Mercancía restringida",
}


def avisar_casos_nuevos(chats: List[Dict]):
    """Notificación en la consola cuando Globix deriva un caso nuevo."""
    derivados = {c["chat_id"]: c for c in chats if c.get("estado") == "Listo para Asesor" and c.get("derivado_at")}
    if "casos_vistos" not in st.session_state:
        st.session_state.casos_vistos = set(derivados)  # al abrir la consola no se avisa lo que ya estaba
        return
    for chat_id in derivados.keys() - st.session_state.casos_vistos:
        chat = derivados[chat_id]
        motivo = MOTIVOS_CORTOS.get(chat.get("motivo_derivacion"), "Derivado por Globix")
        st.toast(f"Nuevo caso: {nombre_mostrado(chat)} · {motivo}", icon=":material/notifications_active:")
    st.session_state.casos_vistos |= set(derivados)


TIPOS_ATENCION = {"cotizacion": "cotización", "faq": "consulta", "guardrail": "mercancía restringida",
                  "mensaje_asesor": "mensaje"}


def texto_primera_atencion(chat: Dict) -> str:
    """'4 min · Globix (cotización)' o 'Pendiente', para el KPI de primera atención útil."""
    inicio, util = _fecha(chat.get("primer_mensaje_at")), _fecha(chat.get("primera_util_at"))
    if not inicio:
        return "—"
    if not util:
        return "Pendiente"
    minutos = max(0, round((util - inicio).total_seconds() / 60))
    quien = "Globix" if chat.get("primera_util_actor") == "bot" else "Asesor"
    tipo = TIPOS_ATENCION.get(chat.get("primera_util_tipo"), chat.get("primera_util_tipo") or "")
    return f"{minutos} min · {quien} ({tipo})"


def panel_detalle(chat: Dict):
    if chat.get("resumen_caso"):
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown("**Resumen del caso**")
                st.badge(MOTIVOS_CORTOS.get(chat.get("motivo_derivacion"), "Derivado"),
                         icon=":material/assignment_ind:", color="orange")
            derivado = _fecha(chat.get("derivado_at"))
            if derivado:
                st.caption(f"Derivado por Globix a las {derivado.strftime('%H:%M')} del {derivado.strftime('%d/%m')}")
            st.markdown(whatsapp_a_markdown(chat["resumen_caso"]))

    with st.container(border=True):
        st.markdown("**Lead**")
        st.metric("Cotización", usd(chat.get("cotizacion_total")))
        paso = min(max(int(chat.get("paso_happy_path") or 1), 1), len(PASOS_HAPPY_PATH))
        st.progress(paso / len(PASOS_HAPPY_PATH), text=f"Paso {paso} de {len(PASOS_HAPPY_PATH)} · {PASOS_HAPPY_PATH[paso - 1]}")
        st.markdown(
            f":material/category: {chat.get('servicio') or '—'}  \n"
            f":material/badge: {tipo_contacto(chat)}  \n"
            f":material/schedule: Último mensaje: {texto_espera(minutos_desde(chat.get('ultimo_mensaje_cliente_at')))}  \n"
            f":material/task_alt: Primera atención útil: {texto_primera_atencion(chat)}"
        )

    with st.container(border=True):
        st.markdown("**Asesor asignado**")
        clave_asesor = f"asesor_{chat['chat_id']}"
        asesor_backend = chat.get("asesor_asignado") if chat.get("asesor_asignado") in ASESORES else None
        if st.session_state.get(f"{clave_asesor}_backend", "∅") != asesor_backend:
            st.session_state[clave_asesor] = asesor_backend
            st.session_state[f"{clave_asesor}_backend"] = asesor_backend
        st.selectbox(
            "Asesor asignado", ASESORES, index=None, placeholder=SIN_ASIGNAR, label_visibility="collapsed",
            key=clave_asesor, on_change=_asignar_asesor, args=(chat["chat_id"], chat.get("estado"), clave_asesor),
        )
        st.caption("Al responder por primera vez, el chat se asigna a quien responde.")

    with st.container(border=True):
        st.markdown("**Estado**")
        opciones = list(ESTADOS)
        actual = chat.get("estado") if chat.get("estado") in opciones else opciones[0]
        clave = f"estado_{chat['chat_id']}"
        # El widget refleja SIEMPRE el estado del backend: si cambió allá (p. ej.
        # Globix derivó al asesor), se sincroniza aquí. Solo un clic del asesor
        # (on_change) escribe en el backend; nunca se compara al refrescar, porque
        # eso revertía las derivaciones hechas por el bot.
        if st.session_state.get(f"{clave}_backend") != actual:
            st.session_state[clave] = actual
            st.session_state[f"{clave}_backend"] = actual
        st.segmented_control(
            "Estado del lead", opciones, required=True, label_visibility="collapsed",
            format_func=lambda e: {"Listo para Asesor": "Asesor"}.get(e, ESTADOS[e]["corto"]),
            key=clave, wrap=False, width="stretch",
            on_change=_cambiar_estado, args=(chat["chat_id"], clave),
        )
        st.caption("Globix solo responde cuando el estado es *Globix*.")

    with st.container(border=True):
        st.markdown("**Acciones**")
        if chat.get("cotizacion_total"):
            revision = estado_revision(chat["chat_id"])
            if revision:
                hora = _fecha(revision.get("timestamp"))
                cuando = hora.strftime("%H:%M del %d/%m") if hora else ""
                if revision["tipo"] == REVISION_VALIDADA:
                    st.badge(f"Validada por {revision.get('asesor')} · {cuando}", icon=":material/verified:", color="green")
                else:
                    st.badge(f"Corregida por {revision.get('asesor')} · {cuando}", icon=":material/edit_note:", color="orange")
                    st.caption(CATEGORIAS_ERROR.get(revision.get("categoria"), "")
                               + (f": {revision['nota']}" if revision.get("nota") else ""))
            else:
                st.caption("Revisa la cotización de Globix: si está bien, envía el PDF formal; si no, corrígela.")
            pdf = None
            try:
                respuesta_pdf = api.get(f"{BACKEND_URL}/api/download-pdf/{chat['chat_id']}")
                pdf = respuesta_pdf.content if respuesta_pdf.status_code == 200 else None
            except Exception:
                pass
            if pdf:
                validada = bool(revision and revision["tipo"] == REVISION_VALIDADA)
                if st.button("Reenviar PDF" if validada else "Validar y enviar PDF", type="primary",
                             icon=":material/send:", width="stretch",
                             help="Envía la proforma formal en PDF al cliente por WhatsApp y registra la cotización como validada."):
                    if enviar_proforma_pdf(chat["chat_id"]):
                        st.toast("Proforma enviada por WhatsApp", icon=":material/check_circle:")
                        st.rerun(scope="app")
                    else:
                        st.toast("No se pudo enviar la proforma", icon=":material/error:")
                if st.button("Corregir cotización", icon=":material/edit:", width="stretch",
                             help="La cotización de Globix tenía un error: regístralo (no se envía nada al cliente)."):
                    dialogo_corregir(chat)
                st.download_button("Descargar proforma", data=pdf, file_name=f"Proforma_Globex_{chat['chat_id']}.pdf",
                                   mime="application/pdf", icon=":material/download:", width="stretch")
            else:
                st.caption("Proforma PDF no disponible (el servidor se reinició).")
        if st.button("Reportar error de Globix", icon=":material/flag:", width="stretch"):
            dialogo_reportar(chat)
        if st.button("Enviar recordatorio", icon=":material/notifications:", width="stretch"):
            # Texto aprobado 05/11: lo firma el asesor; nombre solo si el cliente lo dio
            cot = chat.get("cotizacion_total")
            nombre_cli = chat.get("nombre_cliente")
            saludo = f"¡Hola, {nombre_cli.split()[0]}! 👋" if nombre_cli else "¡Hola! 👋"
            monto_txt = f"de USD {cot:,.2f} " if cot else ""
            nudge = (
                f"{saludo} Soy {st.session_state.usuario_actual['nombre']}, de Globex. "
                f"Tu cotización {monto_txt}sigue vigente. "
                "¿Te ayudo a avanzar con tu compra o tienes alguna duda?"
            )
            if enviar_mensaje(chat["chat_id"], nudge):
                st.toast("Recordatorio enviado", icon=":material/check_circle:")
                st.rerun()


def _campos_error(clave: str):
    categoria = st.selectbox("¿Qué estuvo mal?", list(CATEGORIAS_ERROR), format_func=CATEGORIAS_ERROR.get,
                             index=None, placeholder="Elige una opción", key=f"cat_{clave}")
    nota = st.text_area("Nota (opcional)", max_chars=500, key=f"nota_{clave}",
                        placeholder="Ej.: el cliente dijo 1.5 kg y Globix usó 15 kg")
    return categoria, nota


def _guardar_revision(chat_id: str, tipo: str, categoria: Optional[str], nota: str, mensaje_id=None):
    if not categoria:
        st.toast("Elige qué estuvo mal.", icon=":material/warning:")
        return
    if registrar_revision(chat_id, tipo, categoria, nota, mensaje_id):
        st.toast("Revisión registrada", icon=":material/check_circle:")
        st.rerun()
    else:
        st.error("No se pudo registrar la revisión.", icon=":material/error:")


@st.dialog("Corregir cotización")
def dialogo_corregir(chat: Dict):
    st.caption("Marca qué estuvo mal en la cotización de Globix. No se envía nada al cliente: "
               "luego respóndele tú con los datos correctos.")
    categoria, nota = _campos_error(f"corr_{chat['chat_id']}")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Guardar", type="primary", icon=":material/save:"):
            _guardar_revision(chat["chat_id"], REVISION_CORREGIDA, categoria, nota)


@st.dialog("Reportar error de Globix")
def dialogo_reportar(chat: Dict):
    del_bot = [m for m in fetch_messages(chat["chat_id"]) if (m.get("emisor") or "").lower().startswith("bot")][-15:]
    if not del_bot:
        st.caption("Globix aún no ha enviado mensajes en este chat.")
        return

    def etiqueta(m):
        hora = _fecha(m.get("timestamp"))
        texto = " ".join(separar_opciones(m.get("texto") or "")[0].replace("*", "").split())
        return f"{hora.strftime('%H:%M') if hora else ''} · {texto[:70]}{'…' if len(texto) > 70 else ''}"

    mensaje = st.selectbox("Mensaje de Globix", del_bot[::-1], format_func=etiqueta, key=f"msg_{chat['chat_id']}")
    categoria, nota = _campos_error(f"rep_{chat['chat_id']}")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Reportar", type="primary", icon=":material/flag:"):
            _guardar_revision(chat["chat_id"], REVISION_ERROR, categoria, nota, mensaje["id"])


def estado_revision(chat_id: str) -> Optional[Dict]:
    """Última validación o corrección de la cotización de este chat."""
    revs = [r for r in fetch_revisiones(chat_id) if r.get("tipo") in (REVISION_VALIDADA, REVISION_CORREGIDA)]
    return revs[-1] if revs else None


def pagina_bandeja():
    filtros = barra_lateral()

    @st.fragment(run_every=15 if filtros["auto"] else None)
    def bandeja():
        chats = fetch_chats()
        fila_kpis(chats)
        avisar_casos_nuevos(chats)
        visibles = filtrar(chats, filtros)
        if st.session_state.chat_seleccionado is None and visibles:
            st.session_state.chat_seleccionado = visibles[0]["chat_id"]
        seleccionado = next((c for c in chats if c["chat_id"] == st.session_state.chat_seleccionado), None)

        col_lista, col_chat, col_detalle = st.columns([1.1, 2.1, 1.3], gap="medium")
        with col_lista:
            lista_chats(visibles)
        if seleccionado is None:
            with col_chat:
                st.space("large")
                st.caption("Selecciona una conversación de la bandeja.")
            return
        with col_chat:
            panel_conversacion(seleccionado, filtros["auto"])
        with col_detalle:
            panel_detalle(seleccionado)

    bandeja()


@st.dialog("Limpiar datos de prueba")
def confirmar_limpieza():
    st.write("Se borrarán **todos los chats, mensajes, métricas y proformas** del servidor. No se puede deshacer.")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancelar"):
            st.rerun()
        if st.button("Borrar todo", type="primary", icon=":material/delete:"):
            try:
                r = api.post(f"{BACKEND_URL}/api/admin/clean-data")
                if r.status_code == 200:
                    st.session_state.chat_seleccionado = None
                    st.toast(f"Datos borrados · {r.json().get('pdfs_borrados', 0)} proformas", icon=":material/check_circle:")
            except Exception as e:
                st.toast(f"Error: {e}", icon=":material/error:")
            st.rerun()


NOMBRES_TIPO = {
    "cotizacion": "Cotización",
    "faq": "Pregunta frecuente",
    "derivacion": "Derivación a asesor",
    "menu": "Bienvenida",
    "fuera_de_alcance": "Fuera de alcance",
    "libre": "Respuesta libre",
    "pide_dato": "Pide dato para cotizar",
    "guardrail": "Restringida",
    "error": "Error",
    "recuperacion": "Recuperación",
}


def nombre_tipo(tipo: str) -> str:
    """'bloqueado:codigo' -> 'Bloqueado (código)'; 'cotizacion+faq' -> 'Cotización + Pregunta frecuente'."""
    if not tipo:
        return "—"
    if tipo.startswith("bloqueado:"):
        motivo = {"codigo": "código", "enlace": "enlace", "muy_larga": "muy larga",
                  "monto_no_dado": "monto no dado"}.get(tipo.split(":", 1)[1], tipo.split(":", 1)[1])
        return f"Bloqueado ({motivo})"
    return " + ".join(NOMBRES_TIPO.get(t, t) for t in tipo.split("+"))


def _seg(ms) -> str:
    return f"{ms / 1000:.1f} s" if ms is not None else "—"


def panel_kpi_atencion(kpi: Dict, estricto: Optional[Dict] = None):
    """KPI de impacto: % de leads con primera atención útil en <= 60 min."""
    plazo = kpi.get("plazo_min", 60)
    with st.container(border=True):
        st.markdown(f"**Primera atención útil en ≤ {plazo} min**")
        if not kpi.get("leads_evaluables"):
            en_curso = kpi.get("en_curso", 0)
            st.caption("Aún no hay leads evaluables en este periodo"
                       + (f" ({en_curso} dentro del plazo)." if en_curso else "."))
            return
        li, ls = kpi["ic95"]
        actores = kpi.get("por_actor", {})
        bot, asesor = actores.get("bot", {}), actores.get("asesor", {})
        with st.container(horizontal=True):
            st.metric("Leads a tiempo", f"{kpi['porcentaje']:.0%}", border=True, icon=":material/task_alt:",
                      help=f"{kpi['a_tiempo']} de {kpi['leads_evaluables']} leads · IC 95 % {li:.0%}–{ls:.0%} "
                           "(Clopper-Pearson). Cuenta responder la consulta o pedir un dato indispensable "
                           "(definición del E3); un saludo o el menú no cuentan.")
            st.metric("Tiempo hasta atención útil · p50",
                      f"{kpi['minutos_p50']:.1f} min" if kpi.get("minutos_p50") is not None else "—",
                      border=True, icon=":material/timer:")
            st.metric("Atendidos por Globix / asesor",
                      f"{bot.get('atendidos', 0)} / {asesor.get('atendidos', 0)}", border=True,
                      icon=":material/smart_toy:")
            st.metric("Sin atención útil", kpi.get("sin_atencion_util", 0), border=True,
                      icon=":material/report:", help=f"{kpi.get('en_curso', 0)} leads siguen dentro del plazo")
        nota = f"IC 95 %: {li:.0%}–{ls:.0%} sobre {kpi['leads_evaluables']} leads."
        if estricto and estricto.get("leads_evaluables"):
            ei, es = estricto["ic95"]
            nota += (f" Versión estricta (solo cotización, FAQ, aviso de restricción o asesor): "
                     f"{estricto['porcentaje']:.0%} (IC {ei:.0%}–{es:.0%}).")
        st.caption(nota)


def panel_revision_asesor(rev: Dict):
    """Componente 5 del E3: cotizaciones validadas por el asesor y errores reportados."""
    with st.container(border=True):
        st.markdown("**Revisión del asesor**")
        if not rev or (not rev.get("cotizaciones_revisadas") and not rev.get("errores_reportados")):
            st.caption("Aún no hay cotizaciones validadas ni errores reportados en este periodo.")
            return
        with st.container(horizontal=True):
            if rev.get("cotizaciones_revisadas"):
                li, ls = rev["ic95"]
                st.metric("Cotizaciones validadas sin corrección", f"{rev['porcentaje_validadas']:.0%}", border=True,
                          icon=":material/verified:",
                          help=f"{rev['cotizaciones_validadas']} de {rev['cotizaciones_revisadas']} revisadas · "
                               f"IC 95 % {li:.0%}–{ls:.0%} (Clopper-Pearson)")
            st.metric("Errores reportados", rev.get("errores_reportados", 0), border=True, icon=":material/flag:")
        if rev.get("errores_por_categoria"):
            errores = pd.DataFrame([(CATEGORIAS_ERROR.get(c, c), n) for c, n in rev["errores_por_categoria"].items()],
                                   columns=["Categoría", "Errores"])
            st.bar_chart(errores, x="Categoría", y="Errores", horizontal=True, color=COLOR_MARCA, sort="-Errores",
                         x_label="", y_label="Errores")
        if rev.get("cotizaciones_revisadas"):
            li, ls = rev["ic95"]
            st.caption(f"IC 95 %: {li:.0%}–{ls:.0%} sobre {rev['cotizaciones_revisadas']} cotizaciones revisadas.")


def pagina_metricas():
    with st.sidebar:
        st.markdown(f"**{st.session_state.usuario_actual['nombre']}**")
        if st.button("Cerrar sesión", icon=":material/logout:", type="tertiary"):
            st.session_state.autenticado = False
            st.session_state.usuario_actual = None
            st.rerun()

    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.caption("KPI de primera atención, costo, latencia y comportamiento de Globix.", width="stretch")
        horas = st.segmented_control(
            "Periodo", [1, 24, 168, 0], default=24, required=True, label_visibility="collapsed",
            format_func=lambda h: {1: "1 h", 24: "24 h", 168: "7 días", 0: "Todo"}[h],
        )

    datos = fetch_metricas(horas)
    panel_kpi_atencion(datos.get("kpi_atencion") or {}, datos.get("kpi_atencion_resolutiva"))
    panel_revision_asesor(datos.get("revisiones") or {})
    res = datos.get("resumen", {})
    if not res.get("turnos"):
        st.caption("Aún no hay turnos registrados en este periodo.")
    else:
        espera = res["latencia_total_cliente"]
        with st.container(horizontal=True):
            st.metric("Turnos", res["turnos"], border=True, icon=":material/forum:",
                      help=f"{res['conversaciones']} conversaciones")
            st.metric("Respuesta al cliente · p50", _seg(espera["p50_ms"]), border=True, icon=":material/timer:",
                      help="Desde el primer mensaje del cliente hasta la respuesta (incluye 5 s de espera para agrupar mensajes).")
            st.metric("Respuesta al cliente · p95", _seg(espera["p95_ms"]), border=True, icon=":material/hourglass_bottom:")
            st.metric("Costo por conversación", f"USD {res['costo_por_conversacion_usd']:.4f}", border=True,
                      icon=":material/payments:", help=f"USD {res['costo_por_1000_conversaciones_usd']:.2f} por 1 000 conversaciones")

        col_tipos, col_llm = st.columns([1.2, 1], gap="medium")
        with col_tipos:
            with st.container(border=True, height="stretch"):
                st.markdown("**Cómo respondió Globix**")
                tipos = (pd.DataFrame([(nombre_tipo(t), n) for t, n in res["tipos_respuesta"].items()],
                                      columns=["Tipo", "Turnos"])
                         .groupby("Tipo", as_index=False)["Turnos"].sum()
                         .sort_values("Turnos", ascending=False))
                st.bar_chart(tipos, x="Tipo", y="Turnos", horizontal=True, color=COLOR_MARCA, sort="-Turnos",
                             x_label="", y_label="Turnos")
        with col_llm:
            with st.container(border=True, height="stretch"):
                st.markdown("**Uso del LLM**")
                st.metric("Latencia del LLM · p50 / p95",
                          f"{_seg(res['latencia_llm']['p50_ms'])} / {_seg(res['latencia_llm']['p95_ms'])}")
                st.metric("Tokens por turno", f"{res['tokens_entrada_promedio']:.0f} + {res['tokens_salida_promedio']:.0f}",
                          help="Entrada + salida, promedio por turno")
                st.metric("Costo total del periodo", f"USD {res['costo_total_usd']:.4f}")
                st.caption(f"Precio Groq: USD {res['precio_usd_por_millon']['entrada']} / M entrada · "
                           f"USD {res['precio_usd_por_millon']['salida']} / M salida")

        with st.container(border=True):
            st.markdown("**Últimos turnos**")
            filas = pd.DataFrame(datos.get("ultimos", []))
            if not filas.empty:
                filas = filas.iloc[::-1]
                filas["timestamp"] = pd.to_datetime(filas["timestamp"], errors="coerce")
                filas["tipo_respuesta"] = filas["tipo_respuesta"].map(nombre_tipo)
                st.dataframe(
                    filas[["timestamp", "chat_id", "tipo_respuesta", "llamadas_llm", "latencia_total_ms",
                           "tokens_entrada", "tokens_salida", "costo_usd"]],
                    hide_index=True,
                    column_config={
                        "timestamp": st.column_config.DatetimeColumn("Hora", format="DD/MM HH:mm:ss"),
                        "chat_id": st.column_config.TextColumn("Chat"),
                        "tipo_respuesta": st.column_config.TextColumn("Tipo"),
                        "llamadas_llm": st.column_config.NumberColumn("LLM"),
                        "latencia_total_ms": st.column_config.NumberColumn("Espera (ms)", format="%d"),
                        "tokens_entrada": st.column_config.NumberColumn("Tokens entrada"),
                        "tokens_salida": st.column_config.NumberColumn("Tokens salida"),
                        "costo_usd": st.column_config.NumberColumn("Costo (USD)", format="%.5f"),
                    },
                )

    with st.expander("Zona de administración", icon=":material/admin_panel_settings:"):
        st.caption("Borra los datos de prueba del servidor (chats, mensajes, métricas y proformas).")
        if st.button("Limpiar datos de prueba", icon=":material/delete:"):
            confirmar_limpieza()


# ---------------------------------------------------------------- Navegación

if not st.session_state.autenticado:
    pagina_login()
    st.stop()

st.logo(logo_segun_tema(horizontal=True), icon_image=ICONO, size="large")

paginas = [st.Page(pagina_bandeja, title="Bandeja", icon=":material/inbox:", url_path="bandeja", default=True)]
if st.session_state.usuario_actual["rol"] == "admin":
    paginas.append(st.Page(pagina_metricas, title="Métricas", icon=":material/monitoring:", url_path="metricas"))

pagina = st.navigation(paginas, position="top")
pagina.run()
