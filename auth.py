import base64
import random
from datetime import datetime, timedelta
from io import BytesIO

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
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


# ---------------------------------------------------------------------------
# Captcha de la pantalla de login — una imagen con un código distorsionado
# que hay que escribir para poder entrar, generada 100% con Python/Pillow
# (no depende de Google reCAPTCHA ni de ningún servicio externo). Su único
# objetivo es frenar programas automáticos que prueben contraseñas al vuelo
# — mismo mecanismo ya aplicado en plataforma_ventas y soporte_ti.
# ---------------------------------------------------------------------------
_CAPTCHA_ALFABETO = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # sin 0/O/1/I/l, se prestan a confusión


def _captcha_fuente(tam):
    for ruta in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ):
        try:
            return ImageFont.truetype(ruta, tam)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:
        return ImageFont.load_default()


def _captcha_generar_imagen(codigo: str) -> bytes:
    ancho, alto = 180, 70
    img = Image.new("RGB", (ancho, alto), (245, 245, 243))
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        draw.line(
            (random.randint(0, ancho), random.randint(0, alto), random.randint(0, ancho), random.randint(0, alto)),
            fill=tuple(random.randint(180, 215) for _ in range(3)), width=1,
        )
    fuente = _captcha_fuente(36)
    x = 10
    for ch in codigo:
        capa = Image.new("RGBA", (38, 58), (0, 0, 0, 0))
        ImageDraw.Draw(capa).text((6, 6), ch, font=fuente, fill=tuple(random.randint(20, 90) for _ in range(3)))
        capa = capa.rotate(random.randint(-27, 27), expand=1, resample=Image.BICUBIC)
        img.paste(capa, (x, random.randint(3, 13)), capa)
        x += random.randint(25, 31)
    for _ in range(150):
        draw.point(
            (random.randint(0, ancho - 1), random.randint(0, alto - 1)),
            fill=tuple(random.randint(150, 200) for _ in range(3)),
        )
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _captcha_nuevo():
    codigo = "".join(random.choice(_CAPTCHA_ALFABETO) for _ in range(5))
    st.session_state["_captcha_codigo"] = codigo
    st.session_state["_captcha_imagen"] = _captcha_generar_imagen(codigo)


def _captcha_verificar(texto_escrito: str) -> bool:
    """Compara lo escrito contra el código vigente (sin distinguir mayúsculas
    de minúsculas) y de una vez prepara un código nuevo para el siguiente
    intento — así ningún código se puede reutilizar."""
    codigo_vigente = st.session_state.get("_captcha_codigo", "")
    correcto = bool(texto_escrito) and texto_escrito.strip().upper() == codigo_vigente
    _captcha_nuevo()
    return correcto


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
        if "_captcha_codigo" not in st.session_state:
            _captcha_nuevo()
        # Se guarda en session_state (en vez de mostrarse directo con
        # st.error) porque el mensaje se define justo antes de un
        # st.rerun() — sin esto, el rerun se lleva el mensaje antes de que
        # la persona alcance a verlo.
        mensaje_error = st.session_state.pop("_login_error", None)
        with st.form("login_form"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            col_captcha, col_refrescar = st.columns([2, 1])
            with col_captcha:
                st.image(st.session_state["_captcha_imagen"])
            with col_refrescar:
                st.caption("¿No se lee bien?")
                refrescar = st.form_submit_button("🔄 Otro código", use_container_width=True)
            codigo_escrito = st.text_input("Escribe el código de la imagen")
            if mensaje_error:
                st.error(mensaje_error)
            submitted = st.form_submit_button("Ingresar", use_container_width=True)

            if refrescar:
                _captcha_nuevo()
                st.rerun()
            elif submitted:
                if not _captcha_verificar(codigo_escrito):
                    st.session_state["_login_error"] = (
                        "El código de la imagen no coincide. Escribe el código nuevo que aparece abajo."
                    )
                    st.rerun()
                else:
                    minutos_bloqueo = db.login_esta_bloqueado(username)
                    if minutos_bloqueo:
                        st.session_state["_login_error"] = (
                            f"🔒 Demasiados intentos fallidos con este usuario. Por seguridad, queda "
                            f"bloqueado temporalmente — intenta de nuevo en {minutos_bloqueo} "
                            f"minuto{'s' if minutos_bloqueo != 1 else ''}."
                        )
                        st.rerun()
                    elif do_login(username, password):
                        db.login_limpiar_intentos(username)
                        st.rerun()
                    else:
                        db.login_registrar_intento_fallido(username)
                        st.session_state["_login_error"] = "Usuario o contraseña incorrectos, o el usuario está inactivo."
                        st.rerun()
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
