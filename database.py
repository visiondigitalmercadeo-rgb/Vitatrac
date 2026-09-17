"""Capa de datos — Firestore (Firebase), con un 'modo de práctica' automático
en memoria mientras todavía no tienes tus credenciales de Firebase.

Todo el resto de la aplicación (app_pages/*.py) llama únicamente a las
funciones de este archivo — nunca usa Firestore directamente — así que si
algún día cambias de proveedor de base de datos, solo hay que tocar aquí.

Cómo se eligen las credenciales, en este orden:
  1. `st.secrets["firebase"]`      → para cuando la plataforma esté publicada
                                      en Streamlit Community Cloud.
  2. `serviceAccountKey.json`      → archivo que descargas de Firebase y
     (en la carpeta del proyecto)   colocas junto a este archivo, para uso
                                      local en tu computadora.
  3. Si no se encuentra ninguna    → la app sigue funcionando con datos de
     de las dos anteriores           práctica en memoria (se pierden al
                                      cerrar el servidor), y en pantalla se
                                      avisa que Firebase no está conectado.
"""

import hashlib
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

import bcrypt
import firebase_admin
from firebase_admin import credentials, firestore, storage

import fake_firestore

SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serviceAccountKey.json")

_client = None
MODO_PRACTICA = False  # se actualiza la primera vez que se pide el cliente
_bucket = None  # se actualiza la primera vez que se pide el bucket de Storage


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
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
    primera vez que se necesita y reutilizándolo en el resto de la sesión."""
    global _client, MODO_PRACTICA
    if _client is not None:
        return _client

    cred = _cargar_credenciales()
    if cred is not None:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _client = firestore.client()
        MODO_PRACTICA = False
    else:
        _client = fake_firestore.FakeFirestoreClient()
        MODO_PRACTICA = True
    return _client


def firebase_conectado() -> bool:
    """True si la app está usando tu proyecto real de Firebase (no el modo
    de práctica). Se usa en app.py para mostrar el aviso correspondiente."""
    get_client()
    return not MODO_PRACTICA


# ---------------------------------------------------------------------------
# Firebase Storage — para archivos de material de apoyo que no caben dentro
# de un documento de Firestore. El nombre del bucket se lee de
# `st.secrets["firebase_storage_bucket"]` (un texto que empieza con "gs://",
# tal como aparece en la consola de Firebase → Storage). Si esa clave no está
# configurada, o la app está en modo de práctica, `storage_disponible()`
# devuelve False y las páginas que usan Storage caen automáticamente al
# guardado anterior (base64 dentro del documento).
# ---------------------------------------------------------------------------
def _nombre_bucket_storage():
    try:
        import streamlit as st
        if "firebase_storage_bucket" in st.secrets and st.secrets["firebase_storage_bucket"]:
            return st.secrets["firebase_storage_bucket"]
    except Exception:
        pass
    return None


def _storage_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket

    get_client()  # asegura que firebase_admin ya está inicializado
    if MODO_PRACTICA:
        return None

    nombre_bucket = _nombre_bucket_storage()
    if not nombre_bucket:
        return None

    try:
        _bucket = storage.bucket(nombre_bucket.replace("gs://", ""), app=firebase_admin.get_app())
    except Exception as e:
        print("ERROR AL CONECTAR CON FIREBASE STORAGE:", e)
        return None
    return _bucket


def storage_disponible() -> bool:
    return _storage_bucket() is not None


def subir_archivo_storage(carpeta: str, archivo_subido) -> dict:
    bucket = _storage_bucket()
    if bucket is None:
        raise ValueError(
            "El almacenamiento de archivos grandes (Firebase Storage) todavía no está "
            "configurado en esta plataforma."
        )
    datos = archivo_subido.getvalue()
    ruta = f"{carpeta}/{uuid.uuid4().hex}_{archivo_subido.name}"
    blob = bucket.blob(ruta)
    blob.upload_from_string(datos, content_type=archivo_subido.type or "application/octet-stream")
    return {
        "nombre": archivo_subido.name, "tipo": archivo_subido.type or "application/octet-stream",
        "tamano": len(datos), "storage_path": ruta,
    }


def eliminar_archivos_storage(archivos_lista):
    bucket = _storage_bucket()
    if bucket is None:
        return
    for archivo in (archivos_lista or []):
        ruta = archivo.get("storage_path") if isinstance(archivo, dict) else None
        if not ruta:
            continue
        try:
            bucket.blob(ruta).delete()
        except Exception:
            pass


def url_descarga_archivo_storage(storage_path: str, nombre_descarga: str = None, expira_minutos: int = 60):
    bucket = _storage_bucket()
    if bucket is None:
        return None
    try:
        blob = bucket.blob(storage_path)
        disposicion = f'attachment; filename="{nombre_descarga}"' if nombre_descarga else None
        return blob.generate_signed_url(
            version="v4", expiration=timedelta(minutes=expira_minutos), method="GET",
            response_disposition=disposicion,
        )
    except Exception as e:
        print("ERROR AL GENERAR URL DE DESCARGA DE STORAGE:", e)
        return None


def _doc_to_dict(snapshot):
    data = snapshot.to_dict()
    if data is None:
        return None
    return {**data, "id": snapshot.id}


# ---------------------------------------------------------------------------
# Inicialización y datos de ejemplo
# ---------------------------------------------------------------------------
def init_db(seed_demo: bool = True):
    client = get_client()
    usuarios = list(client.collection("usuarios").limit(1).stream())
    if not usuarios:
        _seed(client, seed_demo)


def _seed(client, seed_demo):
    now = str(date.today())

    users = [
        ("Administrador General", "admin", "admin123", "admin"),
        ("Capacitador Demo", "capacitador", "capacitador123", "capacitador"),
        ("Visor Gerencia", "vista", "vista123", "vista"),
    ]
    for nombre, username, pwd, rol in users:
        client.collection("usuarios").document().set({
            "nombre": nombre, "username": username, "password_hash": hash_password(pwd),
            "rol": rol, "activo": True, "fecha_creacion": now,
        })

    if not seed_demo:
        return

    # Un pequeño ejemplo (una persona, un módulo con un submódulo) para que
    # la plataforma no se vea vacía al explorarla por primera vez — bórralo
    # desde las pestañas correspondientes cuando cargues tus datos reales.
    sede_demo = "Sede Principal"
    client.collection("personal_tiendas").document().set({
        "nombre": "Persona de ejemplo", "tienda": sede_demo, "puesto": "Colaborador", "activo": True,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    modulo_ref = client.collection("capacitacion_modulos").document()
    modulo_ref.set({
        "nombre": "Inducción general", "descripcion": "Módulo de ejemplo — puedes editarlo o eliminarlo.",
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    client.collection("capacitacion_submodulos").document().set({
        "modulo_id": modulo_ref.id, "nombre": "Bienvenida",
        "descripcion": "Submódulo de ejemplo con material de apoyo.",
        "archivos": [], "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def get_user_by_username(username):
    client = get_client()
    for snap in client.collection("usuarios").where("username", "==", username).limit(1).stream():
        return _doc_to_dict(snap)
    return None


def get_usuario(user_id):
    if not user_id:
        return None
    snap = get_client().collection("usuarios").document(user_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def list_usuarios(solo_activos=False):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("usuarios").stream()]
    if solo_activos:
        rows = [r for r in rows if r["activo"]]
    rows.sort(key=lambda r: (r["rol"], r["nombre"]))
    return rows


_PAGINAS_ROL_CONFIG_DOC_ID = "por_rol"


def get_paginas_por_rol():
    """Devuelve qué pestañas ve CADA ROL por defecto — dict {rol: [keys]} —
    editable desde Administración de usuarios → '🧩 Accesos por rol', sin
    tocar código. Si todavía no se ha guardado nada ahí (o solo se guardó
    para algunos roles), completa con el valor de fábrica
    (config.PAGINAS_BASE_POR_ROL)."""
    from config import PAGINAS_BASE_POR_ROL
    client = get_client()
    snap = client.collection("config_paginas").document(_PAGINAS_ROL_CONFIG_DOC_ID).get()
    data = _doc_to_dict(snap) if snap.exists else None
    guardado = (data or {}).get("por_rol") or {}
    return {**PAGINAS_BASE_POR_ROL, **guardado}


def set_paginas_rol(rol, paginas):
    client = get_client()
    doc_ref = client.collection("config_paginas").document(_PAGINAS_ROL_CONFIG_DOC_ID)
    snap = doc_ref.get()
    actual = dict((_doc_to_dict(snap) or {}).get("por_rol") or {}) if snap.exists else {}
    actual[rol] = list(paginas)
    doc_ref.set({"por_rol": actual, "actualizado_en": datetime.now().isoformat(timespec="seconds")})


def create_usuario(nombre, username, password, rol, paginas_extra=None, paginas_removidas=None):
    client = get_client()
    client.collection("usuarios").document().set({
        "nombre": nombre, "username": username, "password_hash": hash_password(password),
        "rol": rol, "activo": True, "fecha_creacion": str(date.today()),
        "paginas_extra": paginas_extra or [], "paginas_removidas": paginas_removidas or [],
    })


def set_usuario_activo(user_id, activo):
    get_client().collection("usuarios").document(user_id).update({"activo": bool(activo)})


def reset_password(user_id, new_password):
    get_client().collection("usuarios").document(user_id).update({"password_hash": hash_password(new_password)})


def update_usuario(user_id, **kwargs):
    """Actualiza datos del usuario (ej. nombre, username, rol). No usar para
    la contraseña: para eso usa reset_password()."""
    kwargs.pop("password", None)
    kwargs.pop("password_hash", None)
    if kwargs:
        get_client().collection("usuarios").document(user_id).update(kwargs)


def delete_usuario(user_id):
    get_client().collection("usuarios").document(user_id).delete()


# ---------------------------------------------------------------------------
# Sesiones "recuérdame" — para que, una vez que alguien inicia sesión, la
# plataforma no lo vuelva a sacar hasta que él mismo cierre sesión (incluso
# si la app se reinicia por un nuevo despliegue, o el navegador se cierra).
# Se guarda un token al azar (nunca la contraseña) en una cookie del
# navegador; aquí solo se guarda el HASH de ese token.
# ---------------------------------------------------------------------------
SESION_RECORDAR_DIAS = 30


def _hash_token_sesion(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_sesion_recordada(user_id):
    token = secrets.token_urlsafe(32)
    expira = datetime.now() + timedelta(days=SESION_RECORDAR_DIAS)
    get_client().collection("sesiones_recordadas").document().set({
        "token_hash": _hash_token_sesion(token), "usuario_id": user_id,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
        "expira_en": expira.isoformat(timespec="seconds"),
    })
    return token


def usuario_desde_token_sesion(token):
    if not token:
        return None
    client = get_client()
    coincidencias = [
        _doc_to_dict(s) for s in
        client.collection("sesiones_recordadas").where("token_hash", "==", _hash_token_sesion(token)).stream()
    ]
    if not coincidencias:
        return None
    sesion = coincidencias[0]
    try:
        if datetime.fromisoformat(sesion["expira_en"]) < datetime.now():
            return None
    except (KeyError, ValueError, TypeError):
        return None
    user = get_usuario(sesion.get("usuario_id"))
    if not user or not user.get("activo", True):
        return None
    return user


def eliminar_sesion_recordada(token):
    if not token:
        return
    client = get_client()
    for s in client.collection("sesiones_recordadas").where("token_hash", "==", _hash_token_sesion(token)).stream():
        client.collection("sesiones_recordadas").document(s.id).delete()


# ---------------------------------------------------------------------------
# Bloqueo temporal de inicio de sesión tras intentos fallidos — protección
# básica contra ataques de "fuerza bruta" (alguien probando contraseñas al
# azar contra un usuario, ya sea a mano o con un programa). Se cuenta por el
# texto de usuario tal cual se escribió en el formulario de login, exista o
# no esa cuenta realmente — así, si alguien intenta adivinar el usuario
# también, el bloqueo se comporta igual y no delata si ese usuario existe.
# Mismo mecanismo ya aplicado en plataforma_ventas y soporte_ti.
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


# ---------------------------------------------------------------------------
# Personal por sede (llamado internamente "tienda" para que coincida con la
# clave "tienda" que se guarda en cada documento — puede representar
# cualquier tipo de sede/sucursal/departamento según config.CAPACITACION_TIENDAS).
# ---------------------------------------------------------------------------
def list_personal_tiendas(tienda=None, solo_activos=True):
    client = get_client()
    query = client.collection("personal_tiendas")
    if tienda:
        query = query.where("tienda", "==", tienda)
    rows = [_doc_to_dict(s) for s in query.stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: (r.get("tienda") or "", r.get("nombre") or ""))
    return rows


def get_personal_tienda(persona_id):
    snap = get_client().collection("personal_tiendas").document(persona_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_personal_tienda(nombre, tienda, puesto=None):
    get_client().collection("personal_tiendas").document().set({
        "nombre": nombre, "tienda": tienda, "puesto": puesto, "activo": True,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_personal_tienda(persona_id, **kwargs):
    if kwargs:
        get_client().collection("personal_tiendas").document(persona_id).update(kwargs)


def delete_personal_tienda(persona_id):
    """Elimina a la persona del listado. Las calificaciones que ya tenga
    registradas no se borran, solo dejan de estar vinculadas a un nombre visible."""
    get_client().collection("personal_tiendas").document(persona_id).delete()


def nombre_personal_tienda(persona_id, personal=None):
    if not persona_id:
        return "—"
    if personal is None:
        personal = list_personal_tiendas(solo_activos=False)
    for p in personal:
        if p["id"] == persona_id:
            return p["nombre"]
    return "—"


# ---------------------------------------------------------------------------
# Capacitación — módulos y submódulos
# ---------------------------------------------------------------------------
def list_modulos():
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("capacitacion_modulos").stream()]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def get_modulo(modulo_id):
    snap = get_client().collection("capacitacion_modulos").document(modulo_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_modulo(nombre, descripcion=None):
    get_client().collection("capacitacion_modulos").document().set({
        "nombre": nombre, "descripcion": descripcion,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_modulo(modulo_id, **kwargs):
    if kwargs:
        get_client().collection("capacitacion_modulos").document(modulo_id).update(kwargs)


def delete_modulo(modulo_id):
    """Elimina el módulo junto con todos sus submódulos, las calificaciones
    (generales y por submódulo), las capacitaciones programadas, las
    asistencias registradas y los diplomas de finalización ligados a él —
    para no dejar nada huérfano."""
    client = get_client()
    for sub in list_submodulos(modulo_id):
        delete_submodulo(sub["id"])
    for c in list_calificaciones(modulo_id=modulo_id):
        client.collection("capacitacion_calificaciones").document(c["id"]).delete()
    for pr in list_capacitacion_programaciones():
        if pr.get("modulo_id") == modulo_id:
            client.collection("capacitacion_programaciones").document(pr["id"]).delete()
    for dip in list_capacitacion_diplomas(modulo_id=modulo_id):
        client.collection("capacitacion_diplomas").document(dip["id"]).delete()
    for a in list_capacitacion_asistencias(modulo_id=modulo_id):
        client.collection("capacitacion_asistencias").document(a["id"]).delete()
    client.collection("capacitacion_modulos").document(modulo_id).delete()


def list_submodulos(modulo_id=None):
    client = get_client()
    query = client.collection("capacitacion_submodulos")
    if modulo_id:
        query = query.where("modulo_id", "==", modulo_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def get_submodulo(submodulo_id):
    snap = get_client().collection("capacitacion_submodulos").document(submodulo_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_submodulo(modulo_id, nombre, descripcion=None, archivos=None):
    get_client().collection("capacitacion_submodulos").document().set({
        "modulo_id": modulo_id, "nombre": nombre, "descripcion": descripcion,
        "archivos": archivos or [], "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_submodulo(submodulo_id, **kwargs):
    if kwargs:
        get_client().collection("capacitacion_submodulos").document(submodulo_id).update(kwargs)


def delete_submodulo(submodulo_id):
    client = get_client()
    for c in list_calificaciones(submodulo_id=submodulo_id):
        client.collection("capacitacion_calificaciones").document(c["id"]).delete()
    for pr in list_capacitacion_programaciones():
        if pr.get("submodulo_id") == submodulo_id:
            client.collection("capacitacion_programaciones").document(pr["id"]).delete()
    for a in list_capacitacion_asistencias(submodulo_id=submodulo_id):
        client.collection("capacitacion_asistencias").document(a["id"]).delete()
    client.collection("capacitacion_submodulos").document(submodulo_id).delete()


# ---------------------------------------------------------------------------
# Capacitación — calificaciones (una por persona + módulo, o por persona +
# submódulo; siempre reemplaza el valor anterior, no suma).
# ---------------------------------------------------------------------------
def list_calificaciones(modulo_id=None, submodulo_id=None, persona_id=None):
    client = get_client()
    query = client.collection("capacitacion_calificaciones")
    if modulo_id:
        query = query.where("modulo_id", "==", modulo_id)
    if persona_id:
        query = query.where("persona_id", "==", persona_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    if submodulo_id is not None:
        rows = [r for r in rows if r.get("submodulo_id") == submodulo_id]
    return rows


def get_calificacion(persona_id, modulo_id, submodulo_id=None):
    coincidencias = [
        c for c in list_calificaciones(modulo_id=modulo_id, persona_id=persona_id)
        if c.get("submodulo_id") == submodulo_id
    ]
    return coincidencias[0] if coincidencias else None


def upsert_calificacion(persona_id, modulo_id, submodulo_id, calificacion, notas=None, horas=None, fecha=None):
    """submodulo_id=None significa que es la calificación general del módulo.
    Si ya existe una calificación para esta persona + módulo (+ submódulo),
    la reemplaza; si no, la crea."""
    existente = get_calificacion(persona_id, modulo_id, submodulo_id)
    data = {
        "persona_id": persona_id, "modulo_id": modulo_id, "submodulo_id": submodulo_id,
        "calificacion": calificacion, "notas": notas,
        "horas": horas, "fecha": str(fecha) if fecha else None,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    client = get_client()
    if existente:
        client.collection("capacitacion_calificaciones").document(existente["id"]).set(data)
    else:
        client.collection("capacitacion_calificaciones").document().set(data)


# ---------------------------------------------------------------------------
# Capacitación — cronograma (programación mensual de capacitaciones): cuándo
# se va a impartir cada módulo/submódulo, a qué sede y quién la da. Es
# independiente de las calificaciones — aquí solo se PLANEA la fecha, no se
# califica a nadie.
# ---------------------------------------------------------------------------
def list_capacitacion_programaciones(mes=None):
    """'mes' es 'YYYY-MM' para filtrar por mes (opcional). Ordenadas por
    fecha, la más próxima primero."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("capacitacion_programaciones").stream()]
    if mes:
        rows = [r for r in rows if (r.get("fecha") or "")[:7] == mes]
    rows.sort(key=lambda r: r.get("fecha") or "")
    return rows


def get_capacitacion_programacion(programacion_id):
    snap = get_client().collection("capacitacion_programaciones").document(programacion_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_capacitacion_programacion(
    fecha, modulo_id, submodulo_id=None, tienda=None, responsable=None, notas=None, modalidad=None,
    link_virtual=None,
):
    get_client().collection("capacitacion_programaciones").document().set({
        "fecha": str(fecha), "modulo_id": modulo_id, "submodulo_id": submodulo_id,
        "tienda": tienda, "responsable": responsable, "notas": notas, "modalidad": modalidad,
        "link_virtual": link_virtual, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_capacitacion_programacion(programacion_id, **kwargs):
    if kwargs:
        get_client().collection("capacitacion_programaciones").document(programacion_id).update(kwargs)


def delete_capacitacion_programacion(programacion_id):
    """Al eliminar la capacitación programada también se borran las
    asistencias que la gente ya haya confirmado para ella."""
    client = get_client()
    for a in list_capacitacion_asistencias(programacion_id=programacion_id):
        client.collection("capacitacion_asistencias").document(a["id"]).delete()
    client.collection("capacitacion_programaciones").document(programacion_id).delete()


# ---------------------------------------------------------------------------
# Capacitación — asistencias: registro de quién confirmó su asistencia a una
# capacitación programada (vía el formulario público que se abre al escanear
# el QR de esa programación).
# ---------------------------------------------------------------------------
def list_capacitacion_asistencias(programacion_id=None, modulo_id=None, submodulo_id=None):
    client = get_client()
    query = client.collection("capacitacion_asistencias")
    if programacion_id:
        query = query.where("programacion_id", "==", programacion_id)
    if modulo_id:
        query = query.where("modulo_id", "==", modulo_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    if submodulo_id is not None:
        rows = [r for r in rows if r.get("submodulo_id") == submodulo_id]
    rows.sort(key=lambda r: r.get("confirmado_en") or "")
    return rows


def create_capacitacion_asistencia(programacion_id, nombre, tienda):
    prog = get_capacitacion_programacion(programacion_id)
    if not prog:
        raise ValueError("Esta capacitación programada ya no existe.")
    data = {
        "programacion_id": programacion_id, "modulo_id": prog.get("modulo_id"),
        "submodulo_id": prog.get("submodulo_id"), "fecha": prog.get("fecha"),
        "nombre": nombre, "tienda": tienda,
        "confirmado_en": datetime.now().isoformat(timespec="seconds"),
    }
    doc_ref = get_client().collection("capacitacion_asistencias").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    return data


def delete_capacitacion_asistencia(asistencia_id):
    get_client().collection("capacitacion_asistencias").document(asistencia_id).delete()


# ---------------------------------------------------------------------------
# Capacitación — diplomas (marca que una persona finalizó un módulo y guarda
# la fecha en la que lo hizo, para poder volver a descargar el mismo diploma
# después sin que la fecha cambie).
# ---------------------------------------------------------------------------
def list_capacitacion_diplomas(persona_id=None, modulo_id=None):
    client = get_client()
    query = client.collection("capacitacion_diplomas")
    if persona_id:
        query = query.where("persona_id", "==", persona_id)
    if modulo_id:
        query = query.where("modulo_id", "==", modulo_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("fecha") or "", reverse=True)
    return rows


def get_capacitacion_diploma(persona_id, modulo_id):
    coincidencias = list_capacitacion_diplomas(persona_id=persona_id, modulo_id=modulo_id)
    return coincidencias[0] if coincidencias else None


def finalizar_modulo_capacitacion(persona_id, modulo_id, tienda, generado_por=None):
    """Marca el módulo como finalizado para esta persona (si no lo estaba
    ya) y devuelve el registro del diploma. Si ya se había finalizado antes,
    NO cambia la fecha original."""
    existente = get_capacitacion_diploma(persona_id, modulo_id)
    if existente:
        return existente
    data = {
        "persona_id": persona_id, "modulo_id": modulo_id, "tienda": tienda,
        "fecha": date.today().isoformat(), "generado_por": generado_por,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    }
    doc_ref = get_client().collection("capacitacion_diplomas").document()
    doc_ref.set(data)
    data["id"] = doc_ref.id
    return data


def delete_capacitacion_diploma(diploma_id):
    get_client().collection("capacitacion_diplomas").document(diploma_id).delete()


# ---------------------------------------------------------------------------
# Hora/fecha — mismo criterio horario que uses en tu región. Cambia el
# desplazamiento de GUATEMALA_TZ si tu operación está en otro país (por
# ejemplo timedelta(hours=-5) para Colombia/Perú/Ecuador).
# ---------------------------------------------------------------------------
GUATEMALA_TZ = timezone(timedelta(hours=-6))


def ahora_guatemala():
    return datetime.now(GUATEMALA_TZ).replace(tzinfo=None)


def hoy_guatemala():
    return ahora_guatemala().date()


def mes_actual() -> str:
    """Mes actual en formato 'YYYY-MM'."""
    return str(hoy_guatemala())[:7]
