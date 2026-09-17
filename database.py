"""Capa de datos — Firestore, con un 'modo de práctica' automático en
memoria mientras todavía no hay credenciales de Firebase configuradas
(idéntico concepto al de la plataforma comercial plataforma_ventas).

IMPORTANTE: este sistema usa el MISMO proyecto de Firebase que
plataforma_ventas (las mismas credenciales que ya están en los secretos de
Streamlit Cloud) — pero todas las colecciones de aquí llevan el prefijo
"it_" para que nunca se mezclen con los datos comerciales.

Todo el resto de la app (app.py, pages/*.py) llama únicamente a las
funciones de este archivo — nunca usa Firestore directamente.
"""

import os
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import bcrypt
import firebase_admin
from firebase_admin import credentials, firestore

import fake_firestore
from config import BASE_DIR, CATEGORIAS_TICKET, EMPRESA_NOMBRE, URGENCIA_DEFECTO, URGENCIA_EMOJI
from utils import orden_trabajo_pdf_bytes

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "serviceAccountKey.json")

_client = None
MODO_PRACTICA = False


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Conexión a Firestore (o modo de práctica en memoria)
# ---------------------------------------------------------------------------
def _cargar_credenciales():
    try:
        import streamlit as st
        if "firebase" in st.secrets:
            return credentials.Certificate(dict(st.secrets["firebase"]))
    except Exception as e:
        import traceback
        print("ERROR AL CARGAR CREDENCIALES DE FIREBASE:", e)
        traceback.print_exc()

    if os.path.exists(SERVICE_ACCOUNT_PATH):
        return credentials.Certificate(SERVICE_ACCOUNT_PATH)

    return None


def get_client():
    """Devuelve el cliente de Firestore (real o de práctica), creándolo la
    primera vez que se necesita y reutilizándolo en el resto de la sesión.
    Usa una app de firebase_admin aparte ("soporte_ti") para no chocar si
    algún día este proceso comparte memoria con el de plataforma_ventas."""
    global _client, MODO_PRACTICA
    if _client is not None:
        return _client

    cred = _cargar_credenciales()
    if cred is not None:
        try:
            app_fb = firebase_admin.get_app("soporte_ti")
        except ValueError:
            app_fb = firebase_admin.initialize_app(cred, name="soporte_ti")
        # Mismo ajuste que plataforma_ventas: el proyecto apunta a la base de
        # datos "vision-digital-ventas-2" (no la "(default)") — ver la nota
        # equivalente en el database.py de plataforma_ventas.
        _client = firestore.client(app=app_fb, database_id="vision-digital-ventas-2")
        MODO_PRACTICA = False
    else:
        _client = fake_firestore.FakeFirestoreClient()
        MODO_PRACTICA = True
    return _client


def firebase_conectado() -> bool:
    get_client()
    return not MODO_PRACTICA


def _doc_to_dict(snap):
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


# ---------------------------------------------------------------------------
# Usuarios de soporte (equipo de TI) — colección "it_usuarios". Es un login
# aparte del de plataforma_ventas: usuario/contraseña propios, sin roles
# finos (todos pueden atender tickets); "es_admin" solo controla quién puede
# agregar/desactivar compañeros del equipo (ver pages/1_Sistema_IT.py).
# ---------------------------------------------------------------------------
def list_it_usuarios(solo_activos=False):
    rows = [_doc_to_dict(s) for s in get_client().collection("it_usuarios").stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: (r.get("nombre") or "").lower())
    return rows


def get_it_usuario(uid):
    snap = get_client().collection("it_usuarios").document(uid).get()
    return _doc_to_dict(snap)


def get_it_usuario_by_username(username):
    username = (username or "").strip().lower()
    if not username:
        return None
    query = get_client().collection("it_usuarios").where("username", "==", username).limit(1)
    for snap in query.stream():
        return _doc_to_dict(snap)
    return None


def create_it_usuario(nombre, username, password, es_admin=False, categorias_acceso=None, correo=None):
    username = username.strip().lower()
    if get_it_usuario_by_username(username):
        raise ValueError(f"Ya existe un usuario de TI con el nombre de usuario '{username}'.")
    doc_ref = get_client().collection("it_usuarios").document()
    doc_ref.set({
        "nombre": nombre.strip(), "username": username, "password_hash": hash_password(password),
        "es_admin": bool(es_admin), "activo": True,
        "categorias_acceso": list(categorias_acceso) if categorias_acceso else [],
        "correo": (correo or "").strip() or None,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def set_it_usuario_activo(uid, activo):
    if not activo:
        _validar_no_es_ultimo_admin_activo(uid, motivo="desactivar")
    get_client().collection("it_usuarios").document(uid).update({"activo": bool(activo)})


def update_it_usuario_password(uid, password):
    get_client().collection("it_usuarios").document(uid).update({"password_hash": hash_password(password)})


# ---------------------------------------------------------------------------
# Bloqueo temporal de inicio de sesión tras intentos fallidos — protección
# básica contra ataques de "fuerza bruta" (alguien probando contraseñas al
# azar contra un usuario, ya sea a mano o con un programa). Se cuenta por el
# texto de usuario tal cual se escribió en el formulario de login, exista o
# no esa cuenta realmente — así, si alguien intenta adivinar el usuario
# también, el bloqueo se comporta igual y no delata si ese usuario existe.
# ---------------------------------------------------------------------------
LOGIN_MAX_INTENTOS = 5
LOGIN_BLOQUEO_MINUTOS = 15


def _login_intentos_doc_id(username: str) -> str:
    doc_id = (username or "").strip().lower()
    return doc_id or "_usuario_vacio_"


def login_esta_bloqueado(username: str):
    """Si este usuario tiene demasiados intentos fallidos recientes, devuelve
    los minutos que le quedan de bloqueo (entero, 1 o más). Si puede
    intentar iniciar sesión normalmente, devuelve None."""
    snap = get_client().collection("login_intentos").document(_login_intentos_doc_id(username)).get()
    if not snap.exists:
        return None
    bloqueado_hasta = (snap.to_dict() or {}).get("bloqueado_hasta")
    if not bloqueado_hasta:
        return None
    try:
        restante = datetime.fromisoformat(bloqueado_hasta) - datetime.now()
    except (ValueError, TypeError):
        return None
    if restante.total_seconds() <= 0:
        return None
    return max(1, int(restante.total_seconds() // 60) + 1)


def login_registrar_intento_fallido(username: str):
    """Suma un intento fallido de este usuario; al llegar a LOGIN_MAX_INTENTOS
    lo bloquea por LOGIN_BLOQUEO_MINUTOS minutos y reinicia el contador."""
    ref = get_client().collection("login_intentos").document(_login_intentos_doc_id(username))
    snap = ref.get()
    intentos = ((snap.to_dict() or {}).get("intentos", 0) if snap.exists else 0) + 1
    datos = {"intentos": intentos, "ultimo_intento": datetime.now().isoformat(timespec="seconds")}
    if intentos >= LOGIN_MAX_INTENTOS:
        datos["intentos"] = 0
        datos["bloqueado_hasta"] = (
            datetime.now() + timedelta(minutes=LOGIN_BLOQUEO_MINUTOS)
        ).isoformat(timespec="seconds")
    ref.set(datos)


def login_limpiar_intentos(username: str):
    """Borra el contador de intentos fallidos de este usuario — se llama en
    cuanto inicia sesión correctamente."""
    get_client().collection("login_intentos").document(_login_intentos_doc_id(username)).delete()


def _admins_activos(excluir_uid=None):
    """Lista de administradores activos, opcionalmente excluyendo un uid
    (para poder preguntar '¿si le quito el admin a este, queda alguien más
    como administrador?')."""
    return [
        u for u in list_it_usuarios(solo_activos=True)
        if u.get("es_admin") and u["id"] != excluir_uid
    ]


def _validar_no_es_ultimo_admin_activo(uid, motivo):
    """Evita dejar el sistema sin ningún administrador activo (nadie podría
    volver a gestionar el equipo). 'motivo' se usa solo para el mensaje de
    error (p. ej. 'quitar el admin a', 'desactivar', 'eliminar')."""
    usuario = get_it_usuario(uid)
    if not usuario or not usuario.get("es_admin") or not usuario.get("activo", True):
        return  # no era admin activo, no hay riesgo de dejar el equipo sin administrador
    if not _admins_activos(excluir_uid=uid):
        raise ValueError(
            f"No puedes {motivo} a '{usuario.get('nombre')}': es el único administrador activo. "
            "Primero vuelve administrador a otro técnico."
        )


def update_it_usuario_perfil(uid, nombre, username, categorias_acceso=None, correo=None):
    """Edita nombre, usuario (login), correo y las categorías de tickets que
    puede atender. El correo es el que recibe la Orden de Trabajo en PDF
    cuando le asignan un ticket (ver enviar_orden_ticket) — puede dejarse
    vacío, simplemente no le llega nada directo a esa persona. No toca
    contraseña, rol ni estado activo/inactivo (ver las funciones dedicadas
    para eso)."""
    nombre = (nombre or "").strip()
    username = (username or "").strip().lower()
    if not nombre or not username:
        raise ValueError("El nombre y el usuario no pueden quedar vacíos.")
    existente = get_it_usuario_by_username(username)
    if existente and existente["id"] != uid:
        raise ValueError(f"Ya existe otro usuario de TI con el nombre de usuario '{username}'.")
    get_client().collection("it_usuarios").document(uid).update({
        "nombre": nombre, "username": username,
        "categorias_acceso": list(categorias_acceso) if categorias_acceso else [],
        "correo": (correo or "").strip() or None,
    })


def categorias_validas_tecnico(tecnico: dict) -> list:
    """Las 'categorías que atiende' guardadas de un técnico, descartando
    cualquiera que ya no exista en config.CATEGORIAS_TICKET (por ejemplo si
    se renombró o se quitó una categoría después de asignársela a alguien).
    Lista vacía = puede atender todas las categorías actuales. Se usa tanto
    en el Tablero (para filtrar a quién se puede asignar un ticket) como en
    Administrador (para mostrar/editar los accesos de cada técnico)."""
    accesos = tecnico.get("categorias_acceso") or []
    return [a for a in accesos if a in CATEGORIAS_TICKET]


def set_it_usuario_admin(uid, es_admin):
    """Sube o quita el permiso de administrador. No deja quitarle el admin
    al único administrador activo que queda."""
    if not es_admin:
        _validar_no_es_ultimo_admin_activo(uid, motivo="quitarle el admin")
    get_client().collection("it_usuarios").document(uid).update({"es_admin": bool(es_admin)})


def delete_it_usuario(uid):
    """Elimina permanentemente a un usuario de TI (no solo desactivarlo). Los
    tickets que haya tenido asignados conservan el nombre en su historial,
    así que no se pierde la trazabilidad. No deja eliminar al único
    administrador activo que queda."""
    _validar_no_es_ultimo_admin_activo(uid, motivo="eliminar")
    get_client().collection("it_usuarios").document(uid).delete()


# ---------------------------------------------------------------------------
# Tickets — colección "it_tickets". Numeración corrida (TI-0001, TI-0002,
# ...), con un "historial" que va guardando cada cambio de estado y cada
# comentario de seguimiento, para tener trazabilidad completa del ticket.
# ---------------------------------------------------------------------------
def _siguiente_numero_ticket():
    rows = [_doc_to_dict(s) for s in get_client().collection("it_tickets").stream()]
    numeros = [r.get("numero") for r in rows if isinstance(r.get("numero"), int)]
    return (max(numeros, default=0)) + 1


def list_tickets(estado=None, categoria=None):
    client = get_client()
    query = client.collection("it_tickets")
    if estado:
        query = query.where("estado", "==", estado)
    if categoria:
        query = query.where("categoria", "==", categoria)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("numero") or 0, reverse=True)
    return rows


def get_ticket(ticket_id):
    snap = get_client().collection("it_tickets").document(ticket_id).get()
    return _doc_to_dict(snap)


def get_ticket_por_numero(numero: int):
    query = get_client().collection("it_tickets").where("numero", "==", numero).limit(1)
    for snap in query.stream():
        return _doc_to_dict(snap)
    return None


def create_ticket(
    nombre_solicitante, correo, telefono, area, categoria, descripcion,
    empresa=None, urgencia=None, foto_b64=None, foto_nombre=None, foto_tipo=None,
):
    numero = _siguiente_numero_ticket()
    ahora = datetime.now().isoformat(timespec="seconds")
    doc_ref = get_client().collection("it_tickets").document()
    datos_ticket = {
        "numero": numero,
        "nombre_solicitante": (nombre_solicitante or "").strip(),
        "correo": (correo or "").strip() or None,
        "telefono": (telefono or "").strip() or None,
        "empresa": (empresa or "").strip() or None,
        "area": (area or "").strip() or None,
        "categoria": categoria,
        "urgencia": urgencia or URGENCIA_DEFECTO,
        "descripcion": (descripcion or "").strip(),
        "foto_b64": foto_b64, "foto_nombre": foto_nombre, "foto_tipo": foto_tipo,
        "estado": "Nuevo",
        "asignado_a_id": None, "asignado_a_nombre": None,
        "historial": [{"tipo": "creado", "detalle": "Ticket creado por el solicitante", "fecha": ahora}],
        "creado_en": ahora,
    }
    doc_ref.set(datos_ticket)
    enviar_avisos_ticket_nuevo(datos_ticket)
    return numero


def asignar_ticket(ticket_id, tecnico_id, tecnico_nombre, autor_nombre=None):
    ahora = datetime.now().isoformat(timespec="seconds")
    ticket = get_ticket(ticket_id)
    historial = (ticket or {}).get("historial") or []
    detalle = f"Asignado a {tecnico_nombre}" if tecnico_nombre else "Se quitó la asignación (sin técnico)"
    historial.append({"tipo": "asignado", "detalle": detalle, "autor": autor_nombre, "fecha": ahora})
    cambios = {"asignado_a_id": tecnico_id, "asignado_a_nombre": tecnico_nombre, "historial": historial}
    if tecnico_nombre and (ticket or {}).get("estado") == "Nuevo":
        cambios["estado"] = "Asignado"
    get_client().collection("it_tickets").document(ticket_id).update(cambios)

    if tecnico_id and tecnico_nombre:
        tecnico = get_it_usuario(tecnico_id)
        correo_tecnico = (tecnico or {}).get("correo")
        if correo_tecnico:
            ticket_actualizado = dict(ticket or {})
            ticket_actualizado.update(cambios)
            numero = ticket_actualizado.get("numero")
            numero_txt = f"TI-{numero:04d}" if isinstance(numero, int) else "TI-____"
            enviar_orden_ticket(
                ticket_actualizado, [correo_tecnico],
                asunto=f"🎫 Se te asignó el ticket {numero_txt} — {ticket_actualizado.get('categoria')}",
            )


def avanzar_ticket(ticket_id, nuevo_estado, autor_nombre=None):
    ahora = datetime.now().isoformat(timespec="seconds")
    ticket = get_ticket(ticket_id)
    historial = (ticket or {}).get("historial") or []
    historial.append({
        "tipo": "estado", "detalle": f"Pasó a '{nuevo_estado}'", "autor": autor_nombre, "fecha": ahora,
    })
    get_client().collection("it_tickets").document(ticket_id).update({"estado": nuevo_estado, "historial": historial})


def reclasificar_ticket(ticket_id, nueva_categoria, autor_nombre=None):
    ahora = datetime.now().isoformat(timespec="seconds")
    ticket = get_ticket(ticket_id)
    historial = (ticket or {}).get("historial") or []
    historial.append({
        "tipo": "categoria", "detalle": f"Reclasificado como '{nueva_categoria}'", "autor": autor_nombre, "fecha": ahora,
    })
    get_client().collection("it_tickets").document(ticket_id).update({"categoria": nueva_categoria, "historial": historial})


def agregar_comentario_ticket(ticket_id, autor_nombre, comentario):
    if not (comentario or "").strip():
        return
    ahora = datetime.now().isoformat(timespec="seconds")
    ticket = get_ticket(ticket_id)
    historial = (ticket or {}).get("historial") or []
    historial.append({
        "tipo": "comentario", "detalle": comentario.strip(), "autor": autor_nombre, "fecha": ahora,
    })
    get_client().collection("it_tickets").document(ticket_id).update({"historial": historial})


def delete_ticket(ticket_id):
    """Elimina un ticket permanentemente (no solo lo mueve de estado). Solo
    debe llamarse desde la UI cuando quien lo pide es administrador (ver
    pages/1_Sistema_IT.py) — aquí no se vuelve a validar el rol porque esta
    función ya recibe el ticket_id desde un botón que solo se dibuja para
    administradores."""
    get_client().collection("it_tickets").document(ticket_id).delete()


# ---------------------------------------------------------------------------
# Avisos por correo (Gmail) — mismo patrón que ya usa la plataforma comercial
# para las Minutas de Tienda: si todavía no están las credenciales
# configuradas, estas funciones simplemente no hacen nada (no rompen el
# resto de la página). Usa la MISMA tabla de secretos ("gmail_notificaciones")
# que plataforma_ventas — si ya la configuraste allá, cópiala tal cual aquí.
# ---------------------------------------------------------------------------
def _smtp_config():
    """Lee las credenciales de Gmail desde st.secrets['gmail_notificaciones']
    (tabla con 'usuario' y 'app_password'). Retorna None si todavía no están
    configuradas."""
    try:
        import streamlit as st
        if "gmail_notificaciones" in st.secrets:
            conf = st.secrets["gmail_notificaciones"]
            if conf.get("usuario") and conf.get("app_password"):
                return {"usuario": conf["usuario"], "app_password": conf["app_password"]}
    except Exception as e:
        import traceback
        print("ERROR AL LEER LAS CREDENCIALES DE CORREO:", e)
        traceback.print_exc()
    return None


def correo_disponible() -> bool:
    """True si ya se configuraron las credenciales de Gmail para mandar
    avisos por correo (ver _smtp_config)."""
    return _smtp_config() is not None


def enviar_correo_aviso(destinatarios, asunto, cuerpo) -> bool:
    """Manda un correo de texto plano a una lista de direcciones, usando la
    cuenta de Gmail configurada. Nunca lanza excepción — si algo falla (sin
    credenciales, sin destinatarios, error de red, etc.) retorna False y el
    detalle queda solo en el log del servidor, para que un problema de
    correo nunca tumbe el resto de la página."""
    destinatarios = [d.strip() for d in (destinatarios or []) if d and d.strip()]
    conf = _smtp_config()
    if not destinatarios or not conf:
        return False
    try:
        msg = MIMEText(cuerpo, "plain", "utf-8")
        msg["Subject"] = asunto
        msg["From"] = formataddr((f"Soporte TI {EMPRESA_NOMBRE}", conf["usuario"]))
        msg["To"] = ", ".join(destinatarios)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(conf["usuario"], conf["app_password"])
            server.sendmail(conf["usuario"], destinatarios, msg.as_string())
        return True
    except Exception as e:
        import traceback
        print("ERROR AL MANDAR CORREO DE AVISO:", e)
        traceback.print_exc()
        return False


def enviar_correo_aviso_adjunto(destinatarios, asunto, cuerpo, adjunto_bytes=None, adjunto_nombre=None) -> bool:
    """Igual que enviar_correo_aviso, pero además permite mandar un archivo
    adjunto (la Orden de Trabajo en PDF — ver utils.orden_trabajo_pdf_bytes
    / enviar_orden_ticket). Si 'adjunto_bytes' es None manda un correo de
    texto plano normal, sin adjunto. Nunca lanza excepción — mismo
    comportamiento a prueba de fallos que enviar_correo_aviso."""
    destinatarios = [d.strip() for d in (destinatarios or []) if d and d.strip()]
    conf = _smtp_config()
    if not destinatarios or not conf:
        return False
    try:
        if adjunto_bytes:
            msg = MIMEMultipart()
            msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
            adjunto = MIMEApplication(adjunto_bytes, _subtype="pdf")
            adjunto.add_header(
                "Content-Disposition", "attachment", filename=adjunto_nombre or "documento.pdf",
            )
            msg.attach(adjunto)
        else:
            msg = MIMEText(cuerpo, "plain", "utf-8")
        msg["Subject"] = asunto
        msg["From"] = formataddr((f"Soporte TI {EMPRESA_NOMBRE}", conf["usuario"]))
        msg["To"] = ", ".join(destinatarios)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(conf["usuario"], conf["app_password"])
            server.sendmail(conf["usuario"], destinatarios, msg.as_string())
        return True
    except Exception as e:
        import traceback
        print("ERROR AL MANDAR CORREO CON ADJUNTO:", e)
        traceback.print_exc()
        return False


def enviar_orden_ticket(ticket: dict, destinatarios: list, asunto: str, cuerpo_extra: str = "") -> bool:
    """Genera la Orden de Trabajo en PDF de 'ticket' (con el logo de la
    empresa del solicitante) y la manda por correo a 'destinatarios'. Nunca
    lanza excepción — si algo falla (armar el PDF, mandar el correo, etc.)
    solo queda en el log del servidor."""
    try:
        numero = ticket.get("numero")
        numero_txt = f"TI-{numero:04d}" if isinstance(numero, int) else "TI-____"
        pdf_bytes = orden_trabajo_pdf_bytes(ticket)
        cuerpo = (
            (cuerpo_extra + "\n\n" if cuerpo_extra else "")
            + f"Se adjunta la Orden de Trabajo del ticket {numero_txt} en PDF."
        )
        return enviar_correo_aviso_adjunto(
            destinatarios, asunto, cuerpo, adjunto_bytes=pdf_bytes, adjunto_nombre=f"{numero_txt}.pdf",
        )
    except Exception as e:
        import traceback
        print("ERROR AL PREPARAR LA ORDEN DE TRABAJO:", e)
        traceback.print_exc()
        return False


def _es_correo_valido(texto) -> bool:
    return bool(texto and _EMAIL_RE.match(texto.strip()))


def correo_es_valido(texto) -> bool:
    """Versión pública de _es_correo_valido — la usa el formulario público
    (app.py) para validar el campo de correo antes de guardar el ticket."""
    return _es_correo_valido(texto)


def get_it_correos_aviso(categoria: str) -> list:
    """Lista de correos del personal de soporte que reciben aviso automático
    cada vez que entra un ticket nuevo de esta categoría (configurable desde
    Administrador → ✉️ Correos de aviso). Vacía si todavía no se ha guardado
    ninguno para esa categoría."""
    snap = get_client().collection("it_config").document(f"correos_aviso_{categoria}").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_it_correos_aviso(categoria: str, correos: list):
    get_client().collection("it_config").document(f"correos_aviso_{categoria}").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def get_url_publica() -> str:
    """Link público de esta app (el que se comparte con los solicitantes para
    reportar problemas), guardado desde Administrador → 📱 Código QR de
    acceso. Se usa para armar tanto el texto informativo como los códigos QR
    por empresa. Cadena vacía si todavía no se ha guardado ninguno."""
    snap = get_client().collection("it_config").document("url_publica").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("url") or ""


def set_url_publica(url: str):
    """Guarda el link público, normalizándolo: le agrega 'https://' si falta
    el esquema, y le quita la '/' final (para que quede limpio al pegarle
    '?empresa=...' en el código QR de cada empresa)."""
    url = (url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    url = url.rstrip("/")
    get_client().collection("it_config").document("url_publica").set({
        "url": url,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def enviar_avisos_ticket_nuevo(ticket: dict):
    """Manda los avisos por correo de un ticket recién creado (con la Orden
    de Solicitud en PDF adjunta — ver enviar_orden_ticket): a los correos de
    soporte configurados para esa categoría, y —si el solicitante dejó un
    correo válido en 'correo'— también a él, para confirmarle que su ticket
    quedó registrado. Se llama automáticamente desde create_ticket; nunca
    lanza excepción, para que un problema de correo nunca impida guardar el
    ticket."""
    try:
        categoria = ticket.get("categoria")
        numero = ticket.get("numero")
        numero_txt = f"TI-{numero:04d}" if isinstance(numero, int) else "TI-____"
        urgencia = ticket.get("urgencia") or URGENCIA_DEFECTO
        urgencia_emoji = URGENCIA_EMOJI.get(urgencia, "")

        # "contacto" es el campo viejo (antes de separar correo y teléfono) —
        # se sigue leyendo aquí solo para que los tickets creados antes de
        # este cambio no se queden sin mostrar ningún dato de contacto.
        datos_contacto = ", ".join(
            filter(None, [ticket.get("correo"), ticket.get("telefono")])
        ) or ticket.get("contacto")

        destinatarios_soporte = get_it_correos_aviso(categoria)
        if destinatarios_soporte:
            cuerpo_soporte = (
                f"Se registró un ticket nuevo de {categoria}.\n\n"
                f"N° de ticket: {numero_txt}\n"
                f"Urgencia: {urgencia_emoji} {urgencia}\n"
                f"Empresa: {ticket.get('empresa') or '—'}\n"
                f"Tienda / área: {ticket.get('area') or '—'}\n"
                f"Solicitante: {ticket.get('nombre_solicitante') or '—'}"
                + (f" ({datos_contacto})" if datos_contacto else "") + "\n\n"
                f"Problema:\n{ticket.get('descripcion') or '—'}\n\n"
                f"Entra al Sistema IT para asignarlo y darle seguimiento."
            )
            # Si es Crítico o Emergencia, se nota desde el asunto del correo
            # (no solo abriéndolo), para que no se pierda entre el resto de
            # avisos de la bandeja de entrada.
            prefijo_urgente = f"{urgencia_emoji} [{urgencia.upper()}] " if urgencia in ("Crítico", "Emergencia") else ""
            enviar_orden_ticket(
                ticket, destinatarios_soporte,
                asunto=f"{prefijo_urgente}🎫 Ticket nuevo {numero_txt} — {categoria}",
                cuerpo_extra=cuerpo_soporte,
            )

        correo_solicitante = (ticket.get("correo") or ticket.get("contacto") or "").strip()
        if _es_correo_valido(correo_solicitante):
            cuerpo_solicitante = (
                f"Hola {ticket.get('nombre_solicitante') or ''},\n\n"
                f"Recibimos tu solicitud de {categoria} y quedó registrada como el ticket {numero_txt}.\n\n"
                f"Problema reportado:\n{ticket.get('descripcion') or '—'}\n\n"
                f"El equipo de TI le dará seguimiento pronto. Puedes consultar el estado en cualquier "
                f"momento desde la pestaña 'Consultar un ticket' de la página de Soporte TI, usando el "
                f"número {numero_txt}."
            )
            enviar_orden_ticket(
                ticket, [correo_solicitante], asunto=f"✅ Recibimos tu ticket {numero_txt}",
                cuerpo_extra=cuerpo_solicitante,
            )
    except Exception as e:
        import traceback
        print("ERROR AL PREPARAR LOS AVISOS DE TICKET NUEVO:", e)
        traceback.print_exc()


# ---------------------------------------------------------------------------
# KPIs del tablero (ver pages/1_Sistema_IT.py) — cuántos tickets van este
# mes, cuántos de cada categoría, y cuánto tiempo llevan AHORA MISMO los
# tickets sentados en cada columna del tablero.
# ---------------------------------------------------------------------------
_ESTADO_DESDE_HISTORIAL_RE = re.compile(r"Pasó a '(.+)'")


def _entro_a_estado_actual(ticket: dict):
    """Fecha (texto ISO) en que 'ticket' entró a su estado ACTUAL
    (ticket['estado']) — reconstruida recorriendo el historial en orden,
    replicando las mismas dos formas en que un ticket cambia de estado:
    (a) avanzar_ticket, que deja una marca explícita "Pasó a 'X'", y
    (b) asignar_ticket, que pasa de 'Nuevo' a 'Asignado' en automático al
    asignarle un técnico por primera vez (sin marca de tipo 'estado'). Si el
    ticket nunca cambió de estado, retorna su fecha de creación."""
    estado_simulado = "Nuevo"
    entrada = ticket.get("creado_en")
    for h in (ticket.get("historial") or []):
        tipo = h.get("tipo")
        if tipo == "estado":
            m = _ESTADO_DESDE_HISTORIAL_RE.match(h.get("detalle") or "")
            if m:
                estado_simulado = m.group(1)
                entrada = h.get("fecha") or entrada
        elif tipo == "asignado" and estado_simulado == "Nuevo" and (h.get("detalle") or "").startswith("Asignado a"):
            estado_simulado = "Asignado"
            entrada = h.get("fecha") or entrada
    return entrada


def fecha_entro_a_estado_actual(ticket: dict):
    """Versión pública de _entro_a_estado_actual — la usa la UI (ver
    pages/1_Sistema_IT.py) para mostrar, por ejemplo, la fecha en que un
    ticket del Historial quedó 'Resuelto'/'Cerrado'."""
    return _entro_a_estado_actual(ticket)


def ticket_es_historico(ticket: dict) -> bool:
    """True si el ticket ya no debe verse en el Tablero sino en la sección
    Historial: lleva un día calendario completo (o más) como 'Resuelto' —
    es decir, se resolvió antes de HOY, no hoy mismo — así el mismo día que
    se resuelve un ticket lo sigues viendo en el tablero, y hasta que
    cambia de día se archiva solo, sin necesidad de moverlo manualmente a
    un estado 'Cerrado'. También cuenta como histórico cualquier ticket que
    haya quedado en el estado 'Cerrado' del flujo viejo (de antes de este
    cambio), para no perder esos registros de vista."""
    estado = ticket.get("estado")
    if estado == "Cerrado":
        return True
    if estado != "Resuelto":
        return False
    entrada = _entro_a_estado_actual(ticket)
    if not entrada:
        return False
    try:
        return datetime.fromisoformat(entrada).date() < datetime.now().date()
    except ValueError:
        return False


def calcular_kpis_tablero(tickets: list, tickets_activos: list = None) -> dict:
    """KPIs para el encabezado del tablero:
    - tickets_mes: cuántos tickets se crearon en el mes calendario actual
      (se calcula sobre 'tickets' — todos, incluyendo los ya archivados a
      Historial, para que el conteo de "cuántos entraron este mes" no
      cambie según si ya se resolvieron o no).
    - por_categoria_mes: {categoria: cantidad} de esos tickets del mes.
    - horas_promedio_por_estado: {estado: horas_promedio} — el tiempo
      promedio que llevan AHORA MISMO los tickets que están actualmente
      sentados en cada columna del tablero (se calcula sobre
      'tickets_activos' — si no se indica, se usa 'tickets' — para no
      contar ahí los que ya se archivaron a Historial, que inflarían el
      promedio de 'Resuelto' con tickets resueltos hace meses). Un estado
      sin ningún ticket en este momento simplemente no aparece en el
      diccionario."""
    if tickets_activos is None:
        tickets_activos = tickets

    ahora = datetime.now()
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tickets_mes = []
    for t in tickets:
        creado_en = t.get("creado_en")
        if not creado_en:
            continue
        try:
            if datetime.fromisoformat(creado_en) >= inicio_mes:
                tickets_mes.append(t)
        except ValueError:
            continue

    por_categoria_mes = {}
    for t in tickets_mes:
        cat = t.get("categoria") or "—"
        por_categoria_mes[cat] = por_categoria_mes.get(cat, 0) + 1

    horas_por_estado = {}
    for t in tickets_activos:
        entrada = _entro_a_estado_actual(t)
        if not entrada:
            continue
        try:
            horas = (ahora - datetime.fromisoformat(entrada)).total_seconds() / 3600
        except ValueError:
            continue
        horas_por_estado.setdefault(t.get("estado"), []).append(max(horas, 0.0))

    horas_promedio_por_estado = {
        estado: (sum(valores) / len(valores)) for estado, valores in horas_por_estado.items()
    }

    return {
        "tickets_mes": len(tickets_mes),
        "por_categoria_mes": por_categoria_mes,
        "horas_promedio_por_estado": horas_promedio_por_estado,
    }


def calcular_kpis_historial(tickets_historicos: list, anio: int, mes: int) -> dict:
    """{empresa: cantidad} de tickets del Historial (ya archivados, ver
    ticket_es_historico) que se resolvieron/cerraron dentro del mes y año
    indicados — para el KPI 'cuántas cerradas por empresa' de la sección
    Historial, con su selector de mes."""
    por_empresa = {}
    for t in tickets_historicos:
        entrada = _entro_a_estado_actual(t)
        if not entrada:
            continue
        try:
            fecha = datetime.fromisoformat(entrada)
        except ValueError:
            continue
        if fecha.year == anio and fecha.month == mes:
            empresa = t.get("empresa") or "—"
            por_empresa[empresa] = por_empresa.get(empresa, 0) + 1
    return por_empresa


def calcular_kpis_dashboard(tickets: list, anio: int, mes: int, categoria: str = None, empresa: str = None) -> dict:
    """KPIs agregados para la pestaña Dashboard, sobre TODOS los tickets del
    sistema (los que siguen activos en el Tablero y los ya archivados a
    Historial), filtrados por mes/año y, opcionalmente, por categoría y/o
    empresa. Retorna:
    - creados: cuántos tickets se CREARON dentro de ese mes (con los
      filtros de categoría/empresa aplicados).
    - por_categoria_creados / por_empresa_creados: desglose de 'creados'
      (siempre sobre todas las categorías/empresas, sin importar el filtro
      — útil para mostrarlo solo cuando el filtro está en "Todos/Todas").
    - cerrados: cuántos tickets quedaron archivados (ver ticket_es_historico)
      DENTRO de ese mes — no importa el mes en que se hayan creado.
    - por_categoria_cerrados / por_empresa_cerrados: desglose de 'cerrados'.
    - horas_promedio_resolucion: horas promedio desde que se creó un ticket
      hasta que se archivó, sobre los tickets cerrados ese mes (con los
      filtros aplicados); None si no hubo ninguno en ese periodo.
    - horas_promedio_por_categoria: {categoria: horas_promedio} — lo mismo
      que 'horas_promedio_resolucion' pero desglosado por rubro (Soporte
      Técnico / Soporte Oracle), sobre los tickets cerrados ese mes (con los
      filtros aplicados). Una categoría sin ningún cerrado ese mes
      simplemente no aparece en el diccionario.
    - horas_resolucion_minima / horas_resolucion_maxima: el tiempo de
      resolución (creación → cierre) más corto y más largo, en horas, entre
      los tickets cerrados ese mes (con los filtros aplicados) — solo el
      número, no de qué ticket se trata (para 'el más rápido' / 'el más
      lento' de los KPIs). None si no hubo ninguno cerrado en ese periodo."""
    def coincide_filtros(t):
        if categoria and t.get("categoria") != categoria:
            return False
        if empresa and t.get("empresa") != empresa:
            return False
        return True

    candidatos = [t for t in tickets if coincide_filtros(t)]

    creados = []
    for t in candidatos:
        creado_en = t.get("creado_en")
        if not creado_en:
            continue
        try:
            fecha = datetime.fromisoformat(creado_en)
        except ValueError:
            continue
        if fecha.year == anio and fecha.month == mes:
            creados.append(t)

    por_categoria_creados, por_empresa_creados = {}, {}
    for t in creados:
        cat, emp = t.get("categoria") or "—", t.get("empresa") or "—"
        por_categoria_creados[cat] = por_categoria_creados.get(cat, 0) + 1
        por_empresa_creados[emp] = por_empresa_creados.get(emp, 0) + 1

    cerrados = []
    horas_resolucion = []
    horas_resolucion_por_categoria = {}
    for t in candidatos:
        if not ticket_es_historico(t):
            continue
        fecha_cierre_txt = _entro_a_estado_actual(t)
        if not fecha_cierre_txt:
            continue
        try:
            fecha_cierre = datetime.fromisoformat(fecha_cierre_txt)
        except ValueError:
            continue
        if fecha_cierre.year != anio or fecha_cierre.month != mes:
            continue
        cerrados.append(t)
        creado_en = t.get("creado_en")
        if creado_en:
            try:
                horas = (fecha_cierre - datetime.fromisoformat(creado_en)).total_seconds() / 3600
                horas_resolucion.append(horas)
                cat = t.get("categoria") or "—"
                horas_resolucion_por_categoria.setdefault(cat, []).append(horas)
            except ValueError:
                pass

    por_categoria_cerrados, por_empresa_cerrados = {}, {}
    for t in cerrados:
        cat, emp = t.get("categoria") or "—", t.get("empresa") or "—"
        por_categoria_cerrados[cat] = por_categoria_cerrados.get(cat, 0) + 1
        por_empresa_cerrados[emp] = por_empresa_cerrados.get(emp, 0) + 1

    return {
        "creados": len(creados),
        "por_categoria_creados": por_categoria_creados,
        "por_empresa_creados": por_empresa_creados,
        "cerrados": len(cerrados),
        "por_categoria_cerrados": por_categoria_cerrados,
        "por_empresa_cerrados": por_empresa_cerrados,
        "horas_promedio_resolucion": (
            sum(horas_resolucion) / len(horas_resolucion) if horas_resolucion else None
        ),
        "horas_promedio_por_categoria": {
            cat: sum(horas) / len(horas) for cat, horas in horas_resolucion_por_categoria.items()
        },
        "horas_resolucion_minima": min(horas_resolucion) if horas_resolucion else None,
        "horas_resolucion_maxima": max(horas_resolucion) if horas_resolucion else None,
    }
