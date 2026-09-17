"""Login del equipo de TI — sistema aparte del de plataforma_ventas (usuario/
contraseña propios, guardados en la colección "it_usuarios"). "es_admin"
controla quién puede entrar a la pestaña de Administrador (administrar
usuarios: crear, editar, restablecer contraseña, subir/quitar admin,
activar/desactivar y eliminar). "categorias_acceso" es aparte: qué tipos de
ticket puede atender cada técnico (se usa solo para filtrar a quién se
puede asignar un ticket, ver pages/1_Sistema_IT.py)."""

import streamlit as st

import database as db
from config import LOGO_SOPORTE_PATH


def current_user():
    return st.session_state.get("it_user")


def do_login(username: str, password: str) -> bool:
    user = db.get_it_usuario_by_username(username)
    if not user or not user.get("activo", True):
        return False
    if not db.check_password(password, user["password_hash"]):
        return False
    st.session_state["it_user"] = {
        "id": user["id"], "nombre": user["nombre"], "username": user["username"],
        "es_admin": bool(user.get("es_admin")),
    }
    return True


def do_logout():
    st.session_state.pop("it_user", None)


# CSS global de todas las páginas internas (se inyecta una vez, desde
# mostrar_logo_sidebar(), que se llama al inicio de app.py y de cada página
# de pages/):
#   1) Agranda el logo de la barra lateral y lo centra en la columna gris —
#      el tamaño máximo que ofrece st.logo por sí solo ("large") se queda
#      chico. OJO: el elemento del logo NO lleva data-testid="stLogo" (esa
#      es solo su clase CSS) — el atributo real es
#      data-testid="stSidebarLogo" (confirmado inspeccionando el DOM
#      renderizado con Playwright); una versión anterior de este CSS
#      apuntaba al selector equivocado y por eso nunca se agrandaba de
#      verdad, aunque el número se seguía subiendo. Se apunta a ambos
#      (clase e id) por si acaso cambian de nuevo en una versión futura de
#      Streamlit. Para centrarlo sin mover el botón de colapsar (⟪), ese
#      botón se saca del flujo normal (position:absolute, arriba a la
#      derecha) y el encabezado centra lo que le queda (el logo) con
#      justify-content.
#   2) Define la animación de parpadeo que usa el chip de urgencia
#      "Emergencia" (ver utils.urgencia_badge_html), para que un ticket de
#      Emergencia salte a la vista de inmediato en el tablero.
_GLOBAL_CSS = """
<style>
[data-testid="stSidebarHeader"] {
    height: auto !important;
    padding: 0.75rem 0.5rem 0.5rem !important;
    position: relative !important;
    justify-content: center !important;
}
[data-testid="stSidebarCollapseButton"] {
    position: absolute !important;
    top: 0.35rem !important;
    right: 0.35rem !important;
}
.stLogo, [data-testid="stSidebarLogo"] {
    height: 6.5rem !important;
    max-height: 6.5rem !important;
    width: auto !important;
    max-width: 100% !important;
}

@keyframes urgencia-parpadeo {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
}
.urgencia-parpadea { animation: urgencia-parpadeo 1s ease-in-out infinite; }
</style>
"""


def mostrar_logo_sidebar():
    """Muestra LOGO_SOPORTE_PATH arriba del listado de páginas de la barra
    lateral (st.logo) e inyecta el CSS global de la app (ver _GLOBAL_CSS
    arriba: agranda el logo y define la animación de "Emergencia"). Se usa
    en app.py y en cada página de pages/. Si el archivo del logo falla, no
    truena la página (igual que el resto de imágenes del sistema)."""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)
    try:
        st.logo(LOGO_SOPORTE_PATH, size="large")
    except Exception:
        pass


def _logo_centrado(path, width):
    import base64
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        st.markdown(
            f"<div style='text-align:center;'><img src='data:image/png;base64,{b64}' width='{width}' /></div>",
            unsafe_allow_html=True,
        )
    except Exception:
        # Si hasta el respaldo (st.image) falla -por ejemplo porque el
        # archivo del logo quedó dañado/incompleto en el despliegue-, que
        # no truene toda la pantalla de inicio de sesión: simplemente se
        # sigue sin mostrar el logo, pero el login se puede usar igual.
        try:
            st.image(path, width=width)
        except Exception:
            pass


def require_login() -> bool:
    """Muestra el formulario de login (o, si todavía no existe ningún
    técnico, el formulario de 'primer arranque' para crear al primero) si no
    hay sesión activa. Debe llamarse al inicio de pages/1_Sistema_IT.py.
    Devuelve True si hay un usuario autenticado."""
    if current_user():
        return True

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        _logo_centrado(LOGO_SOPORTE_PATH, 260)
        st.markdown(
            "<h3 style='text-align:center;margin-top:0.5rem;'>Sistema tickets IT</h3>",
            unsafe_allow_html=True,
        )

        tecnicos_existentes = db.list_it_usuarios()
        if not tecnicos_existentes:
            st.info(
                "👋 Todavía no hay ningún técnico registrado — crea la primera cuenta del equipo de "
                "TI (queda como administrador del panel, para poder agregar a los demás compañeros "
                "después)."
            )
            with st.form("form_primer_tecnico"):
                nombre_0 = st.text_input("Tu nombre completo")
                username_0 = st.text_input("Usuario (sin espacios, ej. jperez)")
                password_0 = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Crear mi cuenta y entrar", use_container_width=True):
                    if not nombre_0.strip() or not username_0.strip() or not password_0:
                        st.error("Completa nombre, usuario y contraseña.")
                    else:
                        try:
                            db.create_it_usuario(nombre_0, username_0, password_0, es_admin=True)
                            if do_login(username_0, password_0):
                                st.rerun()
                        except ValueError as e:
                            st.error(str(e))
            return False

        with st.form("form_login_it"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Iniciar sesión", use_container_width=True):
                minutos_bloqueo = db.login_esta_bloqueado(username)
                if minutos_bloqueo:
                    st.error(
                        f"🔒 Demasiados intentos fallidos con este usuario. Por seguridad, queda "
                        f"bloqueado temporalmente — intenta de nuevo en {minutos_bloqueo} "
                        f"minuto{'s' if minutos_bloqueo != 1 else ''}."
                    )
                elif do_login(username, password):
                    db.login_limpiar_intentos(username)
                    st.rerun()
                else:
                    db.login_registrar_intento_fallido(username)
                    st.error("Usuario o contraseña incorrectos, o la cuenta está desactivada.")
    return False
