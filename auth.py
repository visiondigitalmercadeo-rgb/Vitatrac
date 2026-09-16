import base64
from datetime import datetime, timedelta

import streamlit as st
from streamlit_cookies_controller import CookieController

import database as db
from config import LOGO_PATH

# Nombre de la cookie donde se guarda el token de "recuérdame" — para que,
# una vez que alguien inicia sesión, la plataforma no lo vuelva a sacar hasta
# que él mismo cierre sesión (ni siquiera si la app se reinicia por un nuevo
# despliegue, o cierra y vuelve a abrir el navegador).
_COOKIE_SESION = "vitatrac_sesion"


def _cookies():
    """Controlador de cookies del navegador — una sola instancia por sesión
    de Streamlit (se cachea sola en session_state, ver CookieController)."""
    return CookieController()


def _sincronizar_usuario_sesion(user):
    st.session_state["user"] = {
        "id": user["id"],
        "nombre": user["nombre"],
        "username": user["username"],
        "rol": user["rol"],
        "paginas_extra": user.get("paginas_extra") or [],
        "paginas_removidas": user.get("paginas_removidas") or [],
    }


def _logo_centrado(path, width):
    # Si el archivo del logo no existe (por ejemplo, no se subió todavía al
    # repositorio de GitHub), no debe tumbar toda la pantalla de login — se
    # omite la imagen y solo se ve el nombre de la empresa en texto.
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return
    st.markdown(
        f"<div style='text-align:center;'>"
        f"<img src='data:image/png;base64,{b64}' width='{width}' /></div>",
        unsafe_allow_html=True,
    )


def do_login(username: str, password: str) -> bool:
    user = db.get_user_by_username(username.strip().lower())
    if not user or not user["activo"]:
        return False
    if not db.check_password(password, user["password_hash"]):
        return False
    _sincronizar_usuario_sesion(user)
    # Guarda un token de "recuérdame" en una cookie del navegador, para que
    # esta sesión sobreviva un refresh, cerrar y abrir el navegador, o que la
    # plataforma se reinicie por un nuevo despliegue — hasta que la persona
    # cierre sesión ella misma.
    try:
        token = db.crear_sesion_recordada(user["id"])
        _cookies().set(
            _COOKIE_SESION, token, expires=datetime.now() + timedelta(days=db.SESION_RECORDAR_DIAS),
        )
    except Exception:
        pass
    return True


def do_logout():
    try:
        controller = _cookies()
        token = controller.get(_COOKIE_SESION)
        if token:
            db.eliminar_sesion_recordada(token)
        controller.remove(_COOKIE_SESION)
    except Exception:
        pass
    st.session_state.pop("user", None)


def current_user():
    return st.session_state.get("user")


def require_login():
    """Muestra el formulario de login si no hay sesión activa. Debe llamarse
    al inicio de app.py. Devuelve True si hay un usuario autenticado."""
    controller = None
    try:
        controller = _cookies()
    except Exception:
        controller = None

    if current_user():
        return True

    if controller is not None:
        try:
            token = controller.get(_COOKIE_SESION)
        except Exception:
            token = None
        if token:
            user = db.usuario_desde_token_sesion(token)
            if user:
                _sincronizar_usuario_sesion(user)
                return True

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        _logo_centrado(LOGO_PATH, 320)
        st.markdown("<div style='margin-top:1.8rem;'></div>", unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Ingresar", use_container_width=True)
            if submitted:
                if do_login(username, password):
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos, o el usuario está inactivo.")
        with st.expander("Usuarios de demostración"):
            st.markdown(
                "- **admin** / admin123 — Administrador\n"
                "- **capacitador** / capacitador123 — Capacitador\n"
                "- **vista** / vista123 — Solo vista\n\n"
                "Cámbialos desde 'Administración de usuarios' antes de usar la plataforma con tu equipo real."
            )
    return False


def is_admin():
    u = current_user()
    return u is not None and u["rol"] == "admin"


def is_capacitador():
    u = current_user()
    return u is not None and u["rol"] == "capacitador"


def puede_editar_capacitacion():
    """Quién puede crear/editar módulos, submódulos, el cronograma y las
    calificaciones — administrador y capacitador. 'vista' solo consulta."""
    u = current_user()
    return u is not None and u["rol"] in ("admin", "capacitador")
