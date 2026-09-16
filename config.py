"""Configuración global: rutas, colores (paleta validada de la skill dataviz),
listas de opciones de negocio (plantas, estados, etc.)."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Marca
# ---------------------------------------------------------------------------
EMPRESA_NOMBRE = "Visión Digital"
EMPRESA_LEMA = "Tu punto de impresión"
# Dirección física de la empresa — se usa en el encabezado del PDF de envío
# de Logística (formato "ENVÍO No.", igual al de la libreta física impresa).
EMPRESA_DIRECCION_LINEA1 = '2da. Calle 34-92 "A"'
EMPRESA_DIRECCION_LINEA2 = "Calzada Mateo Flores Zona 7"
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.png")
# Ícono cuadrado (los 4 puntos, fondo azul marino) que se ve en la pestaña del
# navegador — el logo completo (LOGO_PATH) no es cuadrado, así que para esto
# se usa una versión aparte.
FAVICON_PATH = os.path.join(BASE_DIR, "assets", "favicon.png")
# Logo del cliente Phara — se muestra en la parte superior de la pestaña
# Phara en vez de un ícono genérico (ver app_pages/22_Phara.py).
PHARA_LOGO_PATH = os.path.join(BASE_DIR, "assets", "phara_logo.png")
# Firma escaneada de Steven Gabriel — se usa en el diploma de finalización de
# módulo de Capacitación (ver app_pages/16_Capacitacion.py / utils.diploma_pdf_bytes).
FIRMA_STEVEN_PATH = os.path.join(BASE_DIR, "assets", "firma_steven.png")
FIRMA_STEVEN_NOMBRE = "Steven Gabriel"
FIRMA_STEVEN_PUESTO = "Gerente Comercial"
# Firma escaneada para el PDF de "ENVÍO No. ___" de Logística — se coloca
# sobre la línea izquierda ("ENVÍA") (ver utils.pedido_pdf_bytes).
FIRMA_ENVIO_PATH = os.path.join(BASE_DIR, "assets", "firma_envio.png")
FIRMA_ENVIO_NOMBRE = "Carlos de León"
FIRMA_ENVIO_PUESTO = "Jefe de Logística"
BRAND_PINK = "#FF0C82"  # color de marca — solo para chrome de la interfaz (botones, acentos),
                         # NO se usa en las gráficas: ahí se mantiene la paleta validada abajo.

# ---------------------------------------------------------------------------
# Paleta (referencia validada por la skill dataviz — references/palette.md)
# ---------------------------------------------------------------------------
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"

# ---------------------------------------------------------------------------
# Catálogos de negocio
# ---------------------------------------------------------------------------
ROLES = [
    "admin", "vendedor", "vista", "mercadeo", "jefe_planta", "disenador", "disenador_alvaro",
    "jefe_logistica", "repartidor", "jefe_capacitacion", "asistente_capacitacion",
    "anfitriona", "jefe_tienda", "subjefe_tienda", "asesor_ventas", "cajero",
    "jefe_mantenimiento", "jefe_linea", "cliente_phara", "rrhh",
]
ROLES_LABEL = {
    "admin": "Administrador",
    "vendedor": "Vendedor",
    "vista": "Solo vista",
    "mercadeo": "Mercadeo",
    "jefe_planta": "Jefe de planta",
    "disenador": "Diseñador (Nicolás)",
    "disenador_alvaro": "Diseñador (Álvaro)",
    "jefe_logistica": "Jefe de logística",
    "repartidor": "Repartidor",
    "jefe_capacitacion": "Jefe de capacitación",
    "asistente_capacitacion": "Asistente de capacitación",
    "anfitriona": "Anfitriona (tienda)",
    "jefe_tienda": "Jefe de tienda",
    "subjefe_tienda": "Sub jefe de tienda",
    "asesor_ventas": "Asesor de ventas",
    "cajero": "Cajero",
    "jefe_mantenimiento": "Jefe de Mantenimiento",
    # Rol nuevo (pedido por Steven al construir Minutas de Tienda): ve y usa
    # TODA la plataforma igual que un administrador — MENOS "Administración
    # de usuarios" (crear/eliminar usuarios, cambiar roles y contraseñas),
    # que sigue siendo exclusiva de 'admin' por ser la más delicada (ver
    # PAGINAS_BASE_POR_ROL abajo). Es quien le da seguimiento a los
    # pendientes que dejan las Minutas de Tienda.
    "jefe_linea": "Jefe de línea",
    "cliente_phara": "Cliente Phara",
    # Rol nuevo (pedido por Steven): acceso inicial de solo estas 3 pestañas —
    # Capacitación, Minutas de Tienda y NPS.
    "rrhh": "RRHH",
}

# Roles que pertenecen a una tienda específica (necesitan el campo "tienda"
# en su usuario) para el Sistema de Tickets — Tiendas. Son los ÚNICOS roles
# de tienda que tienen usuario/contraseña para iniciar sesión — el resto del
# personal de tienda (asesores de ventas / "Diseñador", acabados, express)
# solo queda como nombre asignado a su tienda (ver PERSONAL_TIENDA_INICIAL y
# la colección "personal_tiendas"), sin acceso al sistema.
ROLES_DE_TIENDA = ["anfitriona", "jefe_tienda", "subjefe_tienda", "asesor_ventas", "cajero"]

# La colección "personal_tiendas" NO guarda un campo "rol" — solo "puesto"
# (texto libre, ver 16_Capacitacion.py y 10_Administracion.py → 'Carga
# inicial de personal'). Para identificar quién es "asesor de ventas" y
# debe aparecer en la pestaña 🎯 Metas de Minutas de Tienda (ver
# 28_Minutas_Tiendas.py) se compara el "puesto" (sin importar mayúsculas
# ni acentos) contra esta lista. En la carga inicial, quien tiene el rol
# 'asesor_ventas' del sistema siempre queda con puesto "Diseñador" — no
# confundir con los diseñadores del tablero de Diseño Gráfico, que es
# otra cosa aparte.
PUESTOS_ASESOR_VENTAS = ["Diseñador", "Disenador", "Asesor de ventas", "Asesor"]

# Dueño de la plataforma: el ÚNICO usuario protegido de forma permanente en
# "Administración de usuarios" — ningún otro administrador puede eliminarlo
# ni cambiarle el rol para quitarle el acceso de administrador (ver
# 10_Administracion.py). Al estar amarrado a un solo nombre de usuario, por
# definición solo puede existir un Dueño a la vez. Para cambiar quién es el
# Dueño, hay que actualizar este valor.
MASTER_ADMIN_USERNAME = "sgabriel"

# ---------------------------------------------------------------------------
# Registro central de todas las pestañas de la plataforma — usado por app.py
# para construir la navegación (st.Page) y por Administración de usuarios
# para poder darle a un usuario en particular acceso extra a pestañas que su
# rol no le da por defecto (ver el campo "paginas_extra" del usuario y
# auth.paginas_extra_visibles_para). "administracion" queda fuera de lo que
# se puede asignar como acceso extra — es un permiso de administrador
# completo (crear/eliminar usuarios, cambiar roles y contraseñas) y nunca
# debe poder concederse por esta vía.
# ---------------------------------------------------------------------------
PAGINAS_REGISTRO = [
    {"key": "inicio", "path": "app_pages/1_Inicio.py", "title": "Inicio", "icon": "🏠"},
    {"key": "prospectos", "path": "app_pages/2_Prospectos_CRM.py", "title": "Prospección (CRM)", "icon": "🧾"},
    {"key": "llamadas", "path": "app_pages/11_Llamadas.py", "title": "Llamadas", "icon": "📞"},
    {"key": "citas", "path": "app_pages/3_Citas_Vendedores.py", "title": "Citas y visitas de vendedores", "icon": "📅"},
    {"key": "mercadeo", "path": "app_pages/4_Visitas_Mercadeo.py", "title": "Visitas de mercadeo", "icon": "🏪"},
    {"key": "cotizaciones", "path": "app_pages/5_Cotizaciones.py", "title": "Cotizaciones", "icon": "💰"},
    {"key": "cotizador_digital", "path": "app_pages/27_Cotizador_Digital.py", "title": "Cotizador Digital", "icon": "🖨️"},
    {"key": "reclamos", "path": "app_pages/6_Reclamos.py", "title": "Reclamos", "icon": "⚠️"},
    {"key": "diseno", "path": "app_pages/12_Diseno_Grafico.py", "title": "Diseño Gráfico - Nicolás", "icon": "🎨"},
    {
        "key": "diseno_alvaro", "path": "app_pages/14_Diseno_Grafico_Alvaro.py",
        "title": "Diseño Gráfico - Álvaro", "icon": "🖌️",
    },
    {"key": "logistica", "path": "app_pages/13_Logistica.py", "title": "Logística", "icon": "🚚"},
    {"key": "ventas", "path": "app_pages/7_Ventas_Diarias.py", "title": "Venta del día", "icon": "🧮"},
    {"key": "ventas_mes", "path": "app_pages/15_Ventas_Por_Mes.py", "title": "Ventas por mes", "icon": "📅"},
    {"key": "capacitacion", "path": "app_pages/16_Capacitacion.py", "title": "Capacitación", "icon": "🎓"},
    {
        "key": "tickets_tienda", "path": "app_pages/17_Tickets_Tienda.py",
        "title": "Sistema Tickets Tiendas", "icon": "🎫",
    },
    {
        "key": "mantenimiento", "path": "app_pages/18_Mantenimiento_Maquinaria.py",
        "title": "Mantenimiento de Maquinaria", "icon": "🔧",
    },
    {
        "key": "cotizador_tecnico", "path": "app_pages/19_Cotizador_Tecnico.py",
        "title": "Cotizador Técnico", "icon": "🖨️",
    },
    {"key": "mant_tiendas", "path": "app_pages/20_Mant_Tiendas.py", "title": "Mant. Tiendas", "icon": "🏬"},
    {
        "key": "minutas_tiendas", "path": "app_pages/28_Minutas_Tiendas.py",
        "title": "Minutas de Tienda", "icon": "📝",
    },
    {"key": "drive", "path": "app_pages/21_Drive.py", "title": "Drive", "icon": "📁"},
    {"key": "phara", "path": "app_pages/22_Phara.py", "title": "Phara", "icon": "📦"},
    {"key": "documentos", "path": "app_pages/23_Documentos.py", "title": "Documentos", "icon": "📄"},
    {"key": "colorado", "path": "app_pages/24_Colorado.py", "title": "Colorado", "icon": "🖨️"},
    {"key": "galaxy", "path": "app_pages/25_Galaxy.py", "title": "Galaxy", "icon": "🖨️"},
    {"key": "nps", "path": "app_pages/26_NPS.py", "title": "NPS", "icon": "😊"},
    {
        "key": "generales", "path": "app_pages/8_Prospectos_Generales.py",
        "title": "Prospectos generales (todos)", "icon": "🌐",
    },
    {"key": "kpis", "path": "app_pages/9_KPIs.py", "title": "KPIs", "icon": "📊"},
    {
        "key": "administracion", "path": "app_pages/10_Administracion.py",
        "title": "Administración de usuarios", "icon": "👥",
    },
]
# Claves asignables como "acceso extra" en Administración de usuarios — todas
# menos 'administracion' (ver nota de seguridad arriba).
PAGINAS_ASIGNABLES_EXTRA = [p["key"] for p in PAGINAS_REGISTRO if p["key"] != "administracion"]

# ---------------------------------------------------------------------------
# Pestañas que cada rol ve POR DEFECTO, antes de sumarle el "acceso extra"
# por usuario (ver PAGINAS_ASIGNABLES_EXTRA arriba) — es la ÚNICA fuente de
# verdad para esto: la usa app.py para armar la navegación real de cada
# usuario al iniciar sesión, y Administración de usuarios para mostrarle al
# admin, al editar a alguien, qué accesos tiene actualmente (los de su rol +
# los extra). Si el acceso de un rol cambia, se cambia aquí — no hace falta
# tocar nada más.
# ---------------------------------------------------------------------------
_PAGINAS_BASE_COMUN = [
    "inicio", "prospectos", "llamadas", "citas", "mercadeo", "cotizaciones", "cotizador_digital", "reclamos",
    "diseno", "diseno_alvaro", "logistica", "ventas", "ventas_mes", "capacitacion", "tickets_tienda",
    "mantenimiento", "cotizador_tecnico", "mant_tiendas", "documentos", "colorado", "galaxy", "generales", "kpis",
]
PAGINAS_BASE_POR_ROL = {
    # admin, vendedor y vista comparten el mismo paquete amplio de pestañas;
    # admin además tiene Administración de usuarios, Drive, Phara, NPS y
    # Minutas de Tienda (exclusivas de administrador).
    "admin": _PAGINAS_BASE_COMUN + ["administracion", "drive", "phara", "nps", "minutas_tiendas"],
    "vendedor": _PAGINAS_BASE_COMUN,
    "vista": _PAGINAS_BASE_COMUN,
    # Visitas de mercadeo y, además, Tickets — Tiendas (solo para configurar
    # tiempos meta / KPIs, no gestiona tickets), control total de Mant.
    # Tiendas, Drive (solo consulta) y Documentos (solo consulta/descarga).
    "mercadeo": ["mercadeo", "tickets_tienda", "mant_tiendas", "drive", "documentos"],
    # Reclamos (cambia el estado), Mantenimiento de Maquinaria, y Mant.
    # Tiendas (solo sube el PDF de cotización mientras está en 'En cotización').
    "jefe_planta": ["reclamos", "mantenimiento", "mant_tiendas"],
    "disenador": ["diseno"],
    "disenador_alvaro": ["diseno_alvaro"],
    "jefe_logistica": ["logistica"],
    # Solo puede actualizar el estado de sus pedidos asignados en Logística.
    "repartidor": ["logistica"],
    "jefe_capacitacion": ["capacitacion"],
    "asistente_capacitacion": ["capacitacion"],
    # Tickets — Tiendas (solo su tienda), control total de Mant. Tiendas (su
    # sucursal), Minutas de Tienda (elabora la minuta y sus pendientes),
    # Drive (solo consulta), y Colorado/Galaxy para dar seguimiento a
    # órdenes de producción.
    "jefe_tienda": ["tickets_tienda", "mant_tiendas", "minutas_tiendas", "drive", "colorado", "galaxy"],
    "subjefe_tienda": ["tickets_tienda", "mant_tiendas", "minutas_tiendas", "drive", "colorado", "galaxy"],
    # Solo Tickets — Tiendas, y solo ven la tienda asignada a su usuario.
    "anfitriona": ["tickets_tienda"],
    "asesor_ventas": ["tickets_tienda"],
    "cajero": ["tickets_tienda"],
    "jefe_mantenimiento": ["mant_tiendas"],
    # Jefe de línea: acceso a TODA la plataforma igual que admin, menos
    # "Administración de usuarios" (ver nota junto a ROLES_LABEL arriba).
    "jefe_linea": _PAGINAS_BASE_COMUN + ["drive", "phara", "nps", "minutas_tiendas"],
    # Cliente externo: solo consulta en Phara.
    "cliente_phara": ["phara"],
    # RRHH: acceso inicial a Capacitación, Minutas de Tienda y NPS.
    "rrhh": ["capacitacion", "minutas_tiendas", "nps"],
}

# ---------------------------------------------------------------------------
# Personal inicial de cada tienda, proporcionado por Steven, para la carga
# masiva desde 'Administración de usuarios' → 'Carga inicial de personal'.
# TODAS estas personas quedan como nombre asignado a su tienda (colección
# "personal_tiendas") para poder elegir quién elabora cada pedido; SOLO las
# que tienen rol 'jefe_tienda', 'subjefe_tienda', 'anfitriona' o 'cajero'
# (ver ROLES_DE_TIENDA) además reciben un usuario/contraseña para iniciar
# sesión — el resto (asesor_ventas / "Diseñador", acabados, express) no
# necesita usuario. Nota: en la lista original, el puesto "Diseñador" en
# tienda corresponde al rol 'asesor_ventas' del sistema (no confundir con
# los roles 'disenador' / 'disenador_alvaro', que son del tablero de Diseño
# Gráfico); los valores "acabados"/"express" en "rol" son solo etiquetas
# descriptivas para agrupar en la carga inicial, ya no son roles reales de
# ROLES/ROLES_LABEL.
# ---------------------------------------------------------------------------
PERSONAL_TIENDA_INICIAL = [
    # Cayalá
    {"nombre": "Hemerson Hernandez", "puesto_original": "Jefe de tienda", "rol": "jefe_tienda", "tienda": "Cayalá"},
    {"nombre": "Josseline Santizo", "puesto_original": "Sub jefe", "rol": "subjefe_tienda", "tienda": "Cayalá"},
    {"nombre": "Dafne Perez", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Otto Garcia", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Melanie Duque", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "William Alvarez", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Jefereson Flores", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Edwin Liska", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Jose Valentin", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Alexander Carvajal", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Karla Ruiz", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Angie Guadalupe", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    {"nombre": "Ana Muñoz", "puesto_original": "Anfitriona", "rol": "anfitriona", "tienda": "Cayalá"},
    {"nombre": "Lesly Orellana", "puesto_original": "Cajera", "rol": "cajero", "tienda": "Cayalá"},
    {"nombre": "Brandos Barillas", "puesto_original": "Acabados", "rol": "acabados", "tienda": "Cayalá"},
    {"nombre": "Mauricio", "puesto_original": "Express", "rol": "express", "tienda": "Cayalá"},
    {"nombre": "Leonel Santizo", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Cayalá"},
    # Vista Hermosa
    {"nombre": "Brenda Rodas", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Jorge Leal", "puesto_original": "Subjefe de tienda", "rol": "subjefe_tienda", "tienda": "Vista Hermosa"},
    {"nombre": "David Sapon", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Christian Cruz", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Rodrigo Velasques", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Madolin Esquizabal", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Jennifer Hernandez", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Catherine Montenegro", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Vista Hermosa"},
    {"nombre": "Andrea Sandoval", "puesto_original": "Cajera", "rol": "cajero", "tienda": "Vista Hermosa"},
    {"nombre": "Fernando Lopez", "puesto_original": "Acabados", "rol": "acabados", "tienda": "Vista Hermosa"},
    # Majadas
    {"nombre": "Luis Crespin", "puesto_original": "Jefe", "rol": "jefe_tienda", "tienda": "Majadas"},
    {"nombre": "Carlos Subuyuj", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Majadas"},
    {"nombre": "Cinthia Flores", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Majadas"},
    {"nombre": "Pedro Cuxil", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "Majadas"},
    {"nombre": "Lourdes Marroquin", "puesto_original": "Cajero", "rol": "cajero", "tienda": "Majadas"},
    {"nombre": "Hugo Yuman", "puesto_original": "Acabados", "rol": "acabados", "tienda": "Majadas"},
    # CAES
    {"nombre": "Paola Sandoval", "puesto_original": "Jefe tienda", "rol": "jefe_tienda", "tienda": "CAES"},
    {"nombre": "Benjamin Reneau", "puesto_original": "Sub jefe tienda", "rol": "subjefe_tienda", "tienda": "CAES"},
    {"nombre": "Cristobal Rodas", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Amalia Gaitán", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Carlos Cruz", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Andrea Bolaños", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Paula Alvizures", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Gabriela Del Aguila", "puesto_original": "Diseñador", "rol": "asesor_ventas", "tienda": "CAES"},
    {"nombre": "Andrea Lemus", "puesto_original": "Anfitriona", "rol": "anfitriona", "tienda": "CAES"},
    {"nombre": "Adriana Choquic", "puesto_original": "Cajera", "rol": "cajero", "tienda": "CAES"},
    {"nombre": "Hector Vasquez", "puesto_original": "Cajero", "rol": "cajero", "tienda": "CAES"},
    {"nombre": "Cristian Gonzalez", "puesto_original": "Acabados", "rol": "acabados", "tienda": "CAES"},
]

PLANTAS = ["Offset", "Digital", "Valloy", "Colorado"]

ESTADOS_PROSPECTO = ["Prospecto", "En negociación", "Cliente (Ganado)", "Perdido"]

TIPOS_LLAMADA = ["Llamada inicial", "Llamada de seguimiento"]

# ---------------------------------------------------------------------------
# Diseño Gráfico (tablero estilo Trello)
# ---------------------------------------------------------------------------
ESTADOS_DISENO = ["Lista de tareas", "Emergencias", "En proceso", "Cambios", "Entregado"]
# Columnas en las que puede caer una solicitud NUEVA (la llena el vendedor).
ESTADOS_DISENO_INICIALES = ["Lista de tareas", "Emergencias"]
# Columnas que solo el diseñador (o el administrador) puede asignar después.
ESTADOS_DISENO_DISENADOR = ["Lista de tareas", "Emergencias", "En proceso", "Cambios", "Entregado"]
DISENO_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB — límite práctico por archivo cuando se guarda
# dentro del documento de Firestore (formato viejo, y respaldo automático si Firebase
# Storage todavía no está configurado — ver database.py: storage_disponible()).
DISENO_ARCHIVO_MAX_BYTES_STORAGE = 200_000_000  # 200 MB — límite cuando el archivo se sube a
# Firebase Storage (permite PSD, AI y otros archivos de diseño pesados). Coincide con el
# límite de subida por defecto de Streamlit; para permitir archivos más grandes también
# hay que agregar [server] maxUploadSize = <MB> en .streamlit/config.toml.
DISENO_ARCHIVOS_MAX = 3  # máximo de archivos adjuntos por solicitud

# ---------------------------------------------------------------------------
# Logística (pedidos AM/PM)
# ---------------------------------------------------------------------------
FRANJAS_PEDIDO = ["AM", "PM"]
ESTADOS_PEDIDO = ["Pendiente", "En ruta", "Entregado", "No entregado"]
ZONAS_CAPITAL = [f"Zona {i}" for i in range(1, 22)]
PEDIDO_FOTO_ENTREGA_MAX_BYTES = 900_000  # ~900 KB — mismo límite práctico que Mantenimiento/Diseño

# Rutas extra de Logística (Compras, Trámites, Papelería) — versión sencilla
# del pedido, para mandados del repartidor que no son un envío de mercadería.
RUTA_EXTRA_TIPOS = ["Compras", "Trámites", "Papelería"]
ESTADOS_RUTA_EXTRA = ["Pendiente", "Hecho"]

# Vendedores adicionales (sin necesitar usuario propio) que también se
# pueden elegir como "vendedor que hizo la venta" en un pedido de Logística,
# además de los usuarios que ya tienen el rol 'vendedor'. Se cargan solos la
# primera vez que arranca la app (ver database._seed_logistica_vendedores) y
# no requieren ningún paso manual.
LOGISTICA_VENDEDORES_INICIAL = [
    "Hemerson Hernandez", "Alejandra Santizo", "Paola Sandoval", "Benjamin Reneau",
    "Brenda Rodas", "Jorge Leal", "Luis Crespin", "Jazmin Solorzano",
]

# Para tipificar cada pedido de Logística según el canal/ruta de venta.
TIPOS_RUTA_PEDIDO = ["Venta Externa", "Venta Tiendas", "Administración", "Compras"]

TIPOS_CITA = ["Cita", "Visita", "Llamada"]
ESTADOS_CITA = ["Programada", "Realizada", "Cancelada", "No asistió"]

ESTADOS_COTIZACION = ["Enviada", "Pendiente", "En negociación", "Aprobada", "Rechazada"]

ESTADOS_VISITA_MERCADEO = ["Pendiente", "Realizada"]
CHECKLIST_DEFAULT = [
    "Exhibición correcta del producto",
    "Material POP colocado",
    "Precios visibles y correctos",
    "Stock disponible",
    "Limpieza y orden del punto de venta",
    "Presencia de competencia relevante",
    "Punto de venta satisfecho con el servicio",
]

ESTADOS_RECLAMO = ["Abierto", "En proceso", "Resuelto", "Cerrado"]

# ---------------------------------------------------------------------------
# Capacitación (módulos / submódulos por tienda)
# ---------------------------------------------------------------------------
CAPACITACION_TIENDAS = ["Cayalá", "Vista Hermosa", "Majadas", "CAES"]
CAPACITACION_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB — mismo límite práctico que Diseño Gráfico
CAPACITACION_ARCHIVOS_MAX = 5  # máximo de archivos adjuntos por submódulo
CAPACITACION_MODALIDADES = ["Virtual", "Presencial"]  # del cronograma de capacitaciones

ESTADOS_PENDIENTE_MERCADEO = ["Pendiente", "En proceso", "Resuelto"]

# ---------------------------------------------------------------------------
# Mantenimiento de Maquinaria (por planta — no confundir con TICKET_TIENDAS,
# que son las tiendas del Sistema de Tickets)
# ---------------------------------------------------------------------------
PLANTAS_MAQUINARIA = ["Offset", "Digital", "Valloy"]
MANTENIMIENTO_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB — mismo límite práctico que Diseño/Capacitación
TIPOS_MANTENIMIENTO = ["Preventivo", "Correctivo"]
# Motivo por el que se cambió una pieza en un mantenimiento — selección
# múltiple porque a veces aplica más de un motivo a la vez. "Otro" pide un
# detalle específico aparte (ver MOTIVO_OTRO_CAMBIO_PIEZA en la página).
MOTIVOS_CAMBIO_PIEZA = ["Desgaste", "Mal uso", "Tema eléctrico", "Adaptación", "Sustitución", "Otro"]

LINEAS_VENTA = [
    "AFICHE",
    "CALENDARIO",
    "MARBETE",
    "TARJETAS DE PRESENTACION",
    "VOLANTES",
    "AGENDAS",
    "FOLDER OFICIO",
    "GIFT CARD",
    "Sticker DTF",
    "MANTA VINILICA",
    "LIBROS",
    "LIBRETAS",
    "MENÚ",
    "EMPAQUE",
    "REVISTAS",
    "PHOTOBOOK",
    "HANG TAG",
    "TARJETAS DE CUMPLEAÑOS",
    "ETIQUETAS",
    "Etiquetas Valloy",
    "FAJAS",
    "MATERIAL BANCARIO",
    "STICKER VINIL COLORADO",
    "ROLL UP",
    "PORTA VASOS",
    "TICKETS",
    "IMPRESIONES",
    "SEPARADORES",
    "STICKER COMIDA",
    "STICKER VARIOS",
    "FOTOGRAFIAS",
    "GAFETES",
    "Bolsas Kraft",
    "MATERIAL PVC",
    "TABLE TENT",
    "CAJAS",
    "BOTONES",
    "TRIFOLIAR",
    "PORTA CREPAS",
    "TARJETA FIDELIDAD",
    "HOJAS MEMBRETADA",
    "LOTERIA",
    "MAPA",
    "BLOCK DE NOTAS",
    "PUBLICIDAD MUNDIAL",
    "PROMOCIONAL MUNDIAL",
    "RASPABLES",
    "BANDEJA COMIDA",
    "INVITACIONES",
    "PAPEL REGALO",
    "DIPLOMAS",
    "Material Tigo",
    "Fotocopias",
    "Sobre Oficio",
    "Otro",
]

# ---------------------------------------------------------------------------
# Sistema de Tickets — Tiendas (fila de clientes nuevos, con check-in por QR
# desde el celular del cliente, estilo Waitwhile)
# ---------------------------------------------------------------------------
TICKET_TIENDAS = CAPACITACION_TIENDAS  # se reutiliza la misma lista de tiendas

# Se quitó la etapa "Esperando"/"Ingresado": desde que el cliente hace
# check-in (por QR o manual) el ticket entra directo en "En atención"
# ("En espera" en el tablero), sin un paso intermedio.
ESTADOS_TICKET = ["En atención", "En elaboración", "Facturado", "Abandono"]

# Catálogo de servicios/productos que el cliente puede seleccionar (varios a
# la vez) al hacer check-in, ya sea desde el QR o registrado manualmente.
TICKET_SERVICIOS = [
    "BANNERS",
    "BOTONES",
    "CANVAS",
    "COMPRA DE MATERIALES",
    "CORTE RECTO",
    "CORTE TROQUEL",
    "COTIZACIÓN",
    "DISEÑO",
    "EMPLASTICADO",
    "ENCUADERNADO",
    "ESCANER",
    "FOTOCOPIA",
    "FOTOESTATICA",
    "FOTOGRAFÍA VISA",
    "FOTOGRAFÍAS",
    "GAFETES PVC",
    "GRABADO CD",
    "IMPRESIÓN A COLOR PAPEL",
    "IMPRESIÓN B/N PAPEL",
    "IMPRESIÓN PVC",
    "Laminado",
    "LONA VINILICA",
    "PLANOS",
    "POSTERS",
    "REDUCCION",
    "STICKERS",
    "TARJETAS DE PRESENTACIÓN",
    "TROQUEL",
    "USO DE COMPUTADORA",
]

# Slug corto (sin acentos/espacios) para usar en el enlace del código QR, por tienda.
TICKET_TIENDA_SLUG = {
    "Cayalá": "cayala",
    "Vista Hermosa": "vistahermosa",
    "Majadas": "majadas",
    "CAES": "caes",
}
TICKET_SLUG_TIENDA = {v: k for k, v in TICKET_TIENDA_SLUG.items()}

# URL pública de la plataforma, usada para armar el enlace/QR de check-in y el
# enlace de la pantalla "Ahora atendiendo". Si algún día cambia el dominio de
# Streamlit Cloud, solo hay que actualizar esto.
APP_URL = "https://vision-digital-ventas.streamlit.app"

# ---------------------------------------------------------------------------
# NPS (Net Promoter Score): encuesta pública de servicio al cliente, con
# check-in por QR — un código por tienda, mismo concepto que el Sistema de
# Tickets — Tiendas de arriba (por eso se reutilizan las mismas 4 tiendas y
# el mismo slug corto para el enlace del QR).
# ---------------------------------------------------------------------------
NPS_TIENDAS = TICKET_TIENDAS
NPS_TIENDA_SLUG = TICKET_TIENDA_SLUG
NPS_SLUG_TIENDA = TICKET_SLUG_TIENDA

# Las 3 "caritas" con las que el cliente responde una pregunta de tipo
# 'carita' — simple a propósito (nada de escalas de 0 a 10 en el celular del
# cliente). "categoria_nps" es a qué categoría del cálculo formal de NPS
# corresponde cada una (ver database.calcular_nps: %promotores - %detractores).
NPS_CARITAS = [
    {"valor": "malo", "emoji": "😠", "label": "Malo", "color": STATUS["critical"], "categoria_nps": "detractor"},
    {"valor": "regular", "emoji": "🙂", "label": "Regular", "color": STATUS["warning"], "categoria_nps": "neutro"},
    {"valor": "excelente", "emoji": "🥳", "label": "Excelente", "color": STATUS["good"], "categoria_nps": "promotor"},
]

# Las 4 preguntas de la encuesta. El texto (y, en la de opción múltiple, las
# opciones) se pueden editar desde NPS → "⚙️ Parametrización" sin tocar
# código — esto es solo el valor de fábrica, la primera vez que se consulta
# y todavía no se ha guardado nada (ver database.get_nps_preguntas). El
# "tipo" de cada pregunta NO se puede cambiar desde la plataforma: 'carita'
# = las 3 caritas de arriba, 'opcion' = opción múltiple (una sola respuesta),
# 'texto' = texto libre opcional.
NPS_PREGUNTAS_INICIAL = [
    {
        "id": "servicio", "tipo": "carita",
        "texto": "¿Cómo estuvo el servicio dentro de Visión Digital?",
    },
    {
        "id": "medio_publicidad", "tipo": "opcion",
        "texto": "¿Por qué medio de publicidad ha visto Visión Digital?",
        "opciones": ["Facebook", "Instagram", "TikTok", "Otro"],
    },
    {
        "id": "recomendaria", "tipo": "carita",
        "texto": "¿Recomendarías Visión Digital a un amigo o familiar?",
    },
    {
        "id": "mejora", "tipo": "texto",
        "texto": "¿Alguna mejora que nos quieras contar? (opcional)",
    },
]

# ---------------------------------------------------------------------------
# Mantenimiento de Tiendas: tablero de solicitudes estilo Trello, mismo
# concepto que el tablero de Diseño Gráfico — el jefe de tienda (o admin)
# reporta qué hay que arreglar en su sucursal, y el 'Jefe de Mantenimiento'
# la va moviendo por el tablero conforme avanza.
# ---------------------------------------------------------------------------
ESTADOS_MANT_TIENDAS = ["Lista de tareas", "Emergencia", "En cotización", "En proceso", "Finalizado"]
ESTADOS_MANT_TIENDAS_INICIALES = ["Lista de tareas", "Emergencia"]
# A qué columna pasa una solicitud al presionar el botón "➡️ Mover a la
# siguiente etapa" — 'Lista de tareas' y 'Emergencia' son dos puertas de
# entrada distintas que confluyen en el mismo siguiente paso (En cotización);
# de ahí en adelante el flujo es lineal. 'Finalizado' no tiene siguiente.
MANT_TIENDA_SIGUIENTE_ESTADO = {
    "Lista de tareas": "En cotización",
    "Emergencia": "En cotización",
    "En cotización": "En proceso",
    "En proceso": "Finalizado",
}
# Bajado de 900 KB/5 fotos (9-sep-2026): una solicitud puede tener FOTOS y
# PDFs de cotización juntos en el MISMO documento de Firestore — con 900 KB
# por archivo, dos o tres fotos (o una foto + una cotización) ya
# codificadas en base64 se pasaban del límite de tamaño de Firestore (1 MiB
# por documento) y la solicitud no se podía guardar (crash "InvalidArgument"
# en vez de un aviso claro — esto es justo lo que le pasó a lcrespin). Ver
# utils.archivos_a_b64_lista / LIMITE_B64_SEGURO_POR_LLAMADA para el techo
# de seguridad que además protege esto (y el resto de la plataforma) en
# código. Si en el futuro se necesitan fotos/PDFs más pesados o en mayor
# cantidad, la solución de fondo es subirlos a Firebase Storage en vez de
# guardarlos dentro del documento — la plataforma ya tiene ese mecanismo
# listo (ver database.py, sección "Firebase Storage"), solo falta
# conectarlo aquí y configurar el bucket.
MANT_TIENDAS_FOTO_MAX_BYTES = 100_000  # ~100 KB por foto
MANT_TIENDAS_FOTOS_MAX = 3
# Cotización: PDFs que sube el jefe de planta mientras la solicitud está en
# la columna "En cotización" — solo el admin puede autorizarla.
MANT_TIENDAS_COTIZACION_MAX_BYTES = 150_000  # ~150 KB por PDF (misma razón que MANT_TIENDAS_FOTO_MAX_BYTES)
MANT_TIENDAS_COTIZACION_MAX_ARCHIVOS = 2

# ---------------------------------------------------------------------------
# Minutas de Tienda: el jefe (o sub jefe) de tienda deja constancia de los
# temas tratados en su reunión (checklist) y de los pendientes que quedaron
# abiertos. El jefe de línea (o admin) les da seguimiento hasta que se
# resuelven — ver database.py, sección "Minutas de Tienda".
# ---------------------------------------------------------------------------
ESTADOS_PENDIENTE_MINUTA = ["Pendiente", "En proceso", "Resuelto"]

# ---------------------------------------------------------------------------
# Cotizador Técnico: ficha de cotización con cálculo automático de pliegos,
# planchas y pasadas de máquina, a partir del catálogo de máquinas y papel
# (ver database.py, sección "Cotizador Técnico"). El catálogo empieza VACÍO
# a propósito — Steven lo carga con sus costos reales, uno por uno desde la
# pestaña o en bloque con la plantilla de Excel (ver
# app_pages/19_Cotizador_Tecnico.py → "⚙️ Catálogo").
# ---------------------------------------------------------------------------
# Combinaciones comunes de tintas (frente + dorso), para que el usuario elija
# rápido en vez de escribir números — "Personalizado" permite cualquier otra.
TECNICO_TINTAS_PRESETS = {
    "4+4 (full color ambos lados)": (4, 4),
    "4+0 (full color un lado)": (4, 0),
    "4+1": (4, 1),
    "2+2": (2, 2),
    "1+1 (un color ambos lados)": (1, 1),
    "1+0 (un color un lado)": (1, 0),
    "Personalizado": None,
}

# Estados de una cotización técnica.
ESTADOS_TECNICO_COTIZACION = ["Borrador", "Cotizado", "Aprobado", "Rechazado"]

# ---------------------------------------------------------------------------
# Historial (pestaña "Historial" dentro de "Ventas por mes"): serie
# histórica año por año, mes por mes, de la Venta total y la Utilidad total
# de la empresa — viene del Excel "VENTAS PARA PLATAFORMA" que llevaba
# Steven aparte. Es independiente del desglose por vendedor/planta que ya
# tienen las pestañas "Ventas" y "Utilidades" de esa misma página.
# ---------------------------------------------------------------------------
HISTORIAL_CATEGORIAS = ["venta", "utilidad"]
HISTORIAL_CATEGORIA_LABEL = {"venta": "Venta", "utilidad": "Utilidad"}

# ---------------------------------------------------------------------------
# Phara: pestaña exclusiva para este cliente — cronograma de entregas +
# tablero de producción estilo Trello (mismo concepto que Diseño Gráfico).
# Solo la ven admin, quien tenga acceso extra otorgado (ver Administración de
# usuarios) y el rol 'cliente_phara' (que solo puede consultar, no editar).
# ---------------------------------------------------------------------------
ESTADOS_PHARA = ["Sherpa", "Pre prensa", "Impresión", "Acabados", "En logística", "Entregado"]
# A partir de qué etapa es obligatorio tener una fecha de entrega asignada.
# Un pedido nace en "Sherpa" sin fecha; en cuanto se mueve a "Pre prensa" (o
# cualquier etapa posterior) el sistema exige que se indique la fecha antes
# de guardar el cambio.
PHARA_ETAPA_FECHA_OBLIGATORIA = "Pre prensa"

# ---------------------------------------------------------------------------
# Documentos: biblioteca de PDFs (legales, políticas, presentaciones, etc.)
# organizada por categoría. Solo el administrador puede subir o eliminar
# documentos; vendedor, vista, mercadeo y administrador pueden consultar y
# descargar (ver app_pages/23_Documentos.py y app.py).
# ---------------------------------------------------------------------------
DOCUMENTOS_CATEGORIAS = ["Legal", "Políticas", "Presentaciones", "Otros"]
DOCUMENTOS_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB — límite práctico dentro del documento de Firestore
DOCUMENTOS_ARCHIVO_MAX_BYTES_STORAGE = 200_000_000  # 200 MB si Firebase Storage está configurado

# ---------------------------------------------------------------------------
# Horarios y Limpieza: pestaña dentro de Minutas de Tienda (a la par de
# "Metas") — un documento de "Horario" y uno de "Limpieza" por tienda, en
# PDF o Excel. Mismos límites de tamaño que Documentos; mismo criterio de
# acceso que Metas de tienda (ver auth.puede_gestionar_metas_tienda).
# ---------------------------------------------------------------------------
TIENDA_DOC_TIPOS = ["Horario", "Limpieza"]
TIENDA_DOC_TIPO_EMOJI = {"Horario": "📅", "Limpieza": "🧹"}
TIENDA_DOC_ARCHIVO_MAX_BYTES = 900_000  # ~900 KB — límite práctico dentro del documento de Firestore
TIENDA_DOC_ARCHIVO_MAX_BYTES_STORAGE = 200_000_000  # 200 MB si Firebase Storage está configurado

# ---------------------------------------------------------------------------
# Colorado: pestaña para generar y dar seguimiento a órdenes de producción de
# la planta Colorado — mismo concepto que Phara (cronograma de entregas +
# tablero de producción estilo Trello + avisos por correo), pero de uso
# interno: vendedores, jefes de tienda y subjefes de tienda (además de
# admin) pueden crear, mover y eliminar órdenes — ver auth.puede_editar_colorado.
# ---------------------------------------------------------------------------
ESTADOS_COLORADO = ["Nuevo", "En producción", "Acabados", "Entregado"]
# Unidades para las dimensiones del arte (ancho x alto) y opciones de tipo de
# color de la orden — usadas en el formulario de la pestaña Colorado.
COLORADO_DIMENSION_UNIDADES = ["Pulgadas", "Metros", "Centímetros", "Milímetros"]
COLORADO_TIPOS_COLOR = ["Blanco y Negro", "Color", "Con clear", "Con blanco"]
# Archivos de referencia adjuntos a una orden (arte, cotización, etc.) —
# reutiliza los mismos límites de tamaño que Diseño Gráfico
# (DISENO_ARCHIVO_MAX_BYTES / DISENO_ARCHIVO_MAX_BYTES_STORAGE), solo cambia
# cuántos archivos se permiten por orden.
PRODUCCION_ARCHIVOS_MAX = 10

# ---------------------------------------------------------------------------
# Galaxy: pestaña idéntica a Colorado (mismo formulario de 15 campos,
# cronograma, tablero de producción y avisos por correo), pero como línea de
# producción / colección de datos totalmente independiente — ver
# auth.puede_editar_galaxy. Reutiliza las mismas listas de unidades y tipos
# de color que Colorado (COLORADO_DIMENSION_UNIDADES / COLORADO_TIPOS_COLOR),
# ya que son genéricas y no específicas de esa planta.
# ---------------------------------------------------------------------------
ESTADOS_GALAXY = ["Nuevo", "En producción", "Acabados", "Entregado"]

# ---------------------------------------------------------------------------
# Drive: pestaña solo para admin, mercadeo y jefes de tienda (jefe_tienda /
# subjefe_tienda) — trae en la plataforma los números que Steven llevaba en
# un Google Sheet aparte ("DASHBOARD VD"), tabla "DATOS GENERALES" y tabla
# "KRISPY 2", con vista numérica y gráfica, y totalmente editable desde aquí
# (no hay sincronización en vivo con el Google Sheet original — los datos
# históricos se cargan una sola vez, la primera vez que arranca la app con
# esta pestaña, y de ahí en adelante se editan directamente aquí).
# ---------------------------------------------------------------------------
DG_MESES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]
# Categorías de la pestaña "Datos generales" (mismo orden en que aparecen en
# el Google Sheet original) y, para cada una, las "entidades" (tienda/línea/
# total) que se pueden consultar por separado.
DG_CATEGORIAS = ["ventas_totales", "por_linea", "flujo", "ticket_promedio"]
DG_CATEGORIA_LABEL = {
    "ventas_totales": "Ventas totales",
    "por_linea": "Ventas por línea",
    "flujo": "Flujo (clientes atendidos)",
    "ticket_promedio": "Ticket promedio",
}
DG_ENTIDADES = {
    "ventas_totales": ["GENERAL", "CAYALA", "VISTA HERMOSA", "MAJADAS", "CAES"],
    "por_linea": ["TIENDA", "DIGITAL", "OFFSET", "COLORADO", "VALLOY"],
    "flujo": ["TOTAL"],
    "ticket_promedio": ["TOTAL"],
}
# Nombre bonito para mostrar en pantalla (las claves de arriba son las que
# usa el Google Sheet original / los datos guardados).
DG_ENTIDAD_LABEL = {
    "GENERAL": "General (todas las tiendas)", "CAYALA": "Cayalá", "VISTA HERMOSA": "Vista Hermosa",
    "MAJADAS": "Majadas", "CAES": "CAES", "TOTAL": "Total",
    "TIENDA": "Tienda", "DIGITAL": "Digital", "OFFSET": "Offset", "COLORADO": "Colorado", "VALLOY": "Valloy",
}
# Años a los que se limita la GRÁFICA (la tabla numérica sí muestra todos los
# años disponibles) — pedido explícito de Steven.
DG_ANIOS_GRAFICA = [2024, 2025, 2026]

# Pestaña "Krispy 2": desglose mensual por tienda y por producto (Bites/Mini).
KRISPY_TIENDAS = ["CAYALA", "VISTA HERMOSA", "CAES", "MAJADAS"]
KRISPY_TIENDA_LABEL = {"CAYALA": "Cayalá", "VISTA HERMOSA": "Vista Hermosa", "CAES": "CAES", "MAJADAS": "Majadas"}
KRISPY_PRODUCTOS = ["bites", "mini"]
KRISPY_PRODUCTO_LABEL = {"bites": "Bites", "mini": "Mini"}
KRISPY_METRICAS = ["unidades", "dinero", "utilidad"]
KRISPY_METRICA_LABEL = {"unidades": "Unidades", "dinero": "Dinero (Q)", "utilidad": "Utilidad (Q)"}
# El Google Sheet original ("KRISPY 2") no tiene ninguna columna de año — los
# datos cargados (Enero a Julio) se guardaron asumiendo que corresponden a
# 2026 (coincide con el lanzamiento de la tienda CAES). Si esto no es
# correcto, se puede corregir año por año directamente desde la pestaña.
KRISPY_ANIO_ASUMIDO = 2026
