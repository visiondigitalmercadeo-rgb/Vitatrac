"""Catálogos y ajustes de marca de VITATRAC — edita aquí para adaptar la
plataforma a tu operación real (nombre, sedes, roles, etc.), sin tener que
tocar el resto del código."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Marca — cámbialo por el nombre/lema reales de tu empresa u organización.
# ---------------------------------------------------------------------------
EMPRESA_NOMBRE = "VITATRAC"
EMPRESA_LEMA = "Su Taller"
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")
FAVICON_PATH = os.path.join(BASE_DIR, "assets", "favicon.png")

# Firma que aparece al calce de los diplomas (opcional). Si FIRMA_PATH no
# existe todavía, el diploma simplemente no dibuja ninguna imagen de firma
# (deja la línea y el nombre/puesto de texto) — coloca aquí una imagen PNG
# con fondo transparente cuando la tengas, del mismo modo que el logo.
FIRMA_PATH = os.path.join(BASE_DIR, "assets", "firma.png")
FIRMA_NOMBRE = "Coordinación de Capacitación"
FIRMA_PUESTO = "VITATRAC"

# URL pública donde quede publicada la plataforma (Streamlit Community Cloud,
# por ejemplo `https://vitatrac.streamlit.app`) — se usa para armar los links
# de los códigos QR de registro de asistencia. Mientras la corras solo en tu
# computadora puedes dejarla como está: los QR simplemente no van a abrir
# hasta que la publiques.
APP_URL = "https://vitatrac.streamlit.app"

# ---------------------------------------------------------------------------
# Sedes / sucursales que se van a capacitar — reemplaza esta lista por tus
# sedes reales (pueden ser tiendas, sucursales, plantas, departamentos,
# clientes, o lo que corresponda a tu operación). El personal, el cronograma
# y las calificaciones se organizan por estos nombres.
# ---------------------------------------------------------------------------
CAPACITACION_TIENDAS = ["Sede Principal"]
CAPACITACION_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB por archivo adjunto (modo de práctica / sin Storage)
CAPACITACION_ARCHIVOS_MAX = 5  # máximo de archivos adjuntos por submódulo
CAPACITACION_MODALIDADES = ["Virtual", "Presencial"]

# ---------------------------------------------------------------------------
# Roles y accesos
# ---------------------------------------------------------------------------
ROLES = ["admin", "capacitador", "vista"]
ROLES_LABEL = {
    "admin": "Administrador",
    "capacitador": "Capacitador",
    "vista": "Solo vista",
}
PAGINAS_REGISTRO = [
    {"key": "inicio", "path": "app_pages/1_Inicio.py", "title": "Inicio", "icon": "🏠"},
    {"key": "capacitacion", "path": "app_pages/2_Capacitacion.py", "title": "Capacitación", "icon": "🎓"},
    {
        "key": "administracion", "path": "app_pages/3_Administracion.py",
        "title": "Administración de usuarios", "icon": "👥",
    },
]
PAGINAS_ASIGNABLES_EXTRA = [p["key"] for p in PAGINAS_REGISTRO if p["key"] != "administracion"]

# Qué pestañas ve cada rol por defecto (editable en vivo desde Administración
# de usuarios → '🧩 Accesos por rol', sin tocar código — esto es solo el
# valor de fábrica la primera vez que arranca la plataforma).
PAGINAS_BASE_POR_ROL = {
    "admin": ["inicio", "capacitacion", "administracion"],
    "capacitador": ["inicio", "capacitacion"],
    "vista": ["inicio", "capacitacion"],
}
