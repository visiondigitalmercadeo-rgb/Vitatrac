import streamlit as st

import auth
import database as db
import public_capacitacion
from config import EMPRESA_NOMBRE, FAVICON_PATH, LOGO_PATH, PAGINAS_REGISTRO

st.set_page_config(page_title=f"{EMPRESA_NOMBRE}", page_icon=FAVICON_PATH, layout="wide")

try:
    st.logo(LOGO_PATH, size="large")
    # st.logo limita la altura a ~32px por defecto; la agrandamos un poco
    # manteniendo la proporción original del logo (se define solo el alto,
    # el ancho se ajusta automáticamente).
    st.markdown(
        """
        <style>
        img[data-testid="stSidebarLogo"] {
            height: 4.2rem;
            max-height: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
except Exception:
    pass

db.init_db(seed_demo=True)

# ---------------------------------------------------------------------------
# Ruta pública de registro de asistencia por QR — NO requiere haber iniciado
# sesión, así que se atiende aquí mismo, antes del login, y se detiene la
# ejecución.
# ---------------------------------------------------------------------------
_qp_capacitacion = st.query_params.get("capacitacion")
if _qp_capacitacion:
    public_capacitacion.render_registro(_qp_capacitacion)
    st.stop()

if not db.firebase_conectado():
    st.warning(
        "⚠️ **Firebase todavía no está conectado.** Estás viendo la plataforma en "
        "**modo de práctica**: los datos son temporales y se pierden al cerrar el servidor. "
        "Sigue los pasos del README para conectar tu proyecto de Firebase y guardar datos de verdad.",
        icon="⚠️",
    )

if not auth.require_login():
    st.stop()

user = auth.current_user()
rol = user["rol"]

# Todas las páginas se construyen a partir de config.PAGINAS_REGISTRO (una
# sola fuente de verdad), para que Administración de usuarios pueda ofrecer
# exactamente esas mismas pestañas como "acceso extra" por usuario, más
# abajo.
paginas_por_key = {
    p["key"]: st.Page(p["path"], title=p["title"], icon=p["icon"], default=(p["key"] == "inicio"))
    for p in PAGINAS_REGISTRO
}

# Qué pestañas ve cada rol por defecto: se arma a partir de
# db.get_paginas_por_rol() (única fuente de verdad en tiempo real — editable
# desde Administración de usuarios → '🧩 Accesos por rol' sin tocar código;
# si nunca se ha guardado nada ahí, cae al valor de fábrica de
# config.PAGINAS_BASE_POR_ROL).
paginas_por_rol_actual = db.get_paginas_por_rol()

# Accesos individuales de este usuario en particular, por encima de lo que le
# da su rol. 'administracion' nunca se puede tocar por esta vía, para que
# nunca se use para dar -o accidentalmente quitar- acceso de administrador
# completo.
paginas_removidas_usuario = set(user.get("paginas_removidas") or []) - {"administracion"}

pages = [
    paginas_por_key[key] for key in paginas_por_rol_actual.get(rol, [])
    if key in paginas_por_key and key not in paginas_removidas_usuario
]

paginas_ya_incluidas = set(pages)
for key_extra in (user.get("paginas_extra") or []):
    if key_extra == "administracion" or key_extra in paginas_removidas_usuario:
        continue
    pagina_extra = paginas_por_key.get(key_extra)
    if pagina_extra and pagina_extra not in paginas_ya_incluidas:
        pages.append(pagina_extra)
        paginas_ya_incluidas.add(pagina_extra)

# Red de seguridad: si por un rol eliminado, mal escrito o sin pestañas
# configuradas el usuario se quedara sin ninguna página, st.navigation()
# truena con una pantalla de error en vez de dejarlo entrar. Mejor mostrarle
# al menos "Inicio" y que un admin le revise sus accesos.
if not pages and "inicio" in paginas_por_key:
    pages = [paginas_por_key["inicio"]]

nav = st.navigation(pages)
nav.run()
