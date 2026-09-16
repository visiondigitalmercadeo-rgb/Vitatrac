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
import json
import math
import os
import secrets
import smtplib
import uuid
from datetime import date, datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import bcrypt
import firebase_admin
from firebase_admin import credentials, firestore, storage

import fake_firestore
from config import (
    BASE_DIR, CHECKLIST_DEFAULT, EMPRESA_NOMBRE, LOGISTICA_VENDEDORES_INICIAL,
)

SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "serviceAccountKey.json")

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
        # NOTA: se apunta explícitamente a la base de datos "vision-digital-ventas-2"
        # (en vez de la "(default)") porque la base "(default)" del proyecto quedó
        # con un problema de conexión desde el lado de Google tras activar el plan
        # Blaze (error "Invalid database id (default)"). Los datos originales ya
        # fueron migrados (exportados e importados) a esta base nueva, que funciona
        # con normalidad. Si en el futuro Firebase confirma que "(default)" volvió
        # a funcionar, se puede quitar el parámetro database_id para volver a usarla.
        _client = firestore.client(database_id="vision-digital-ventas-2")
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
# Firebase Storage — para archivos grandes que no caben dentro de un
# documento de Firestore (por ejemplo, PSD/AI de Diseño Gráfico). El nombre
# del bucket se lee de `st.secrets["firebase_storage_bucket"]` (un texto que
# empieza con "gs://", tal como aparece en la consola de Firebase → Storage).
# Si esa clave no está configurada, o la app está en modo de práctica,
# `storage_disponible()` devuelve False y las páginas que usan Storage caen
# automáticamente al guardado anterior (base64 dentro del documento).
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
    """Devuelve el bucket de Firebase Storage, o None si no está disponible
    (todavía no se configuró `firebase_storage_bucket` en los secretos, o la
    app está en modo de práctica). Se crea una sola vez y se reutiliza."""
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
    """True si Firebase Storage está listo para usarse (bucket configurado y
    conectado). Las páginas lo usan para decidir si suben archivos grandes a
    Storage o si caen al guardado anterior dentro del documento."""
    return _storage_bucket() is not None


def subir_archivo_storage(carpeta: str, archivo_subido) -> dict:
    """Sube un archivo (de st.file_uploader) a Firebase Storage, dentro de
    'carpeta/', con un nombre único para que dos archivos con el mismo
    nombre no se sobrescriban. Retorna {"nombre", "tipo", "tamano",
    "storage_path"} para guardar en Firestore — SIN el contenido del
    archivo, así el documento se mantiene liviano. Lanza ValueError si
    Storage no está disponible."""
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


def subir_archivos_storage_lista(carpeta: str, archivos_subidos, max_bytes, max_archivos=3) -> list:
    """Versión de subir_archivo_storage() para varios archivos a la vez
    (st.file_uploader con accept_multiple_files=True). Lanza ValueError si
    se suben más de max_archivos, o si alguno pesa más de max_bytes —
    ANTES de subir nada, para no dejar archivos huérfanos en Storage."""
    archivos_subidos = archivos_subidos or []
    if len(archivos_subidos) > max_archivos:
        raise ValueError(
            f"Puedes adjuntar máximo {max_archivos} archivos (subiste {len(archivos_subidos)}). "
            "Quita alguno e intenta de nuevo."
        )
    for archivo in archivos_subidos:
        if len(archivo.getvalue()) > max_bytes:
            raise ValueError(
                f"El archivo '{archivo.name}' pesa {len(archivo.getvalue()) / 1_000_000:.1f} MB; el máximo "
                f"permitido por archivo es {max_bytes / 1_000_000:.0f} MB."
            )
    return [subir_archivo_storage(carpeta, archivo) for archivo in archivos_subidos]


def eliminar_archivos_storage(archivos_lista):
    """Borra de Firebase Storage los archivos de la lista que tengan
    'storage_path' (los guardados como base64 dentro del documento no se
    tocan, no hay nada que borrar en Storage). Limpieza best-effort: si
    Storage no está disponible, o un archivo puntual ya no existe, no
    lanza error — esto se usa después de reemplazar o eliminar archivos,
    y no debe poder bloquear esas acciones."""
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
    """Genera un enlace temporal de descarga directa (firmado, válido por
    `expira_minutos`) para un archivo guardado en Firebase Storage. Retorna
    None si Storage no está disponible o si algo falla al generarlo."""
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
    _seed_logistica_vendedores(client)
    _seed_dg_datos(client)
    _seed_krispy_datos(client)
    _seed_historial_vpm(client)


def _seed_logistica_vendedores(client):
    """Carga la lista inicial de LOGISTICA_VENDEDORES_INICIAL (config.py) en
    la colección 'logistica_vendedores' la primera vez que arranca la app —
    independiente de si ya hay usuarios, para que este agregado funcione
    aunque la plataforma ya esté en uso."""
    existentes = list(client.collection("logistica_vendedores").limit(1).stream())
    if existentes:
        return
    for nombre in LOGISTICA_VENDEDORES_INICIAL:
        client.collection("logistica_vendedores").document().set({
            "nombre": nombre, "activo": True,
            "creado_en": datetime.now().isoformat(timespec="seconds"),
        })


def _seed(client, seed_demo):
    now = str(date.today())

    users = [
        ("Administrador General", "admin", "admin123", "admin"),
        ("Visor Gerencia", "vista", "vista123", "vista"),
        ("Juan Pérez", "juan", "vendedor123", "vendedor"),
        ("María López", "maria", "vendedor123", "vendedor"),
        ("Carlos Ramírez", "carlos", "vendedor123", "vendedor"),
    ]
    ids = {}
    for nombre, username, pwd, rol in users:
        ref = client.collection("usuarios").document()
        ref.set({
            "nombre": nombre, "username": username, "password_hash": hash_password(pwd),
            "rol": rol, "activo": True, "fecha_creacion": now,
        })
        ids[username] = ref.id

    if not seed_demo:
        return

    juan, maria, carlos = ids["juan"], ids["maria"], ids["carlos"]
    today = date.today()

    prospectos = [
        ("Imprenta El Sol, S.A.", "1234567-8", juan, "Prospecto"),
        ("Distribuidora Central", "2233445-6", maria, "En negociación"),
        ("Editorial Horizonte", "9988776-5", carlos, "Cliente (Ganado)"),
        ("Empaques del Norte", "5544332-1", juan, "Perdido"),
        ("Publicidad Maya", "7766554-3", maria, "Prospecto"),
    ]
    prospecto_ids = []
    for nombre, nit, vendedor_id, estado in prospectos:
        ref = client.collection("prospectos").document()
        ref.set({
            "nombre_cliente": nombre, "nit": nit, "telefono": "5555-0000",
            "email": "contacto@ejemplo.com", "direccion": "Zona 10, Ciudad de Guatemala",
            "vendedor_id": vendedor_id, "fecha_registro": str(today - timedelta(days=10)),
            "fecha_seguimiento": str(today + timedelta(days=2)),
            "recordatorio": "Llamar para confirmar interés",
            "notas": "Prospecto de ejemplo (dato semilla)", "estado": estado,
        })
        prospecto_ids.append(ref.id)

    client.collection("cotizaciones").document().set({
        "prospecto_id": prospecto_ids[2], "vendedor_id": carlos,
        "fecha_contacto": str(today - timedelta(days=8)), "fecha_cotizacion": str(today - timedelta(days=5)),
        "numero_cotizacion": "COT-0001", "monto": 15400.0, "estado": "Aprobada", "notas": "Cotización de ejemplo",
    })
    client.collection("cotizaciones").document().set({
        "prospecto_id": prospecto_ids[1], "vendedor_id": maria,
        "fecha_contacto": str(today - timedelta(days=3)), "fecha_cotizacion": str(today - timedelta(days=1)),
        "numero_cotizacion": "COT-0002", "monto": 8200.0, "estado": "Enviada", "notas": "Cotización de ejemplo",
    })

    for vendedor_id, cliente, tipo, dias, estado in [
        (juan, "Imprenta El Sol, S.A.", "Cita", -2, "Realizada"),
        (juan, "Empaques del Norte", "Llamada", 1, "Programada"),
        (maria, "Distribuidora Central", "Visita", 0, "Programada"),
        (carlos, "Editorial Horizonte", "Cita", -5, "Realizada"),
    ]:
        client.collection("citas").document().set({
            "vendedor_id": vendedor_id, "prospecto_id": None, "cliente_nombre": cliente, "tipo": tipo,
            "fecha": str(today + timedelta(days=dias)), "hora": "10:00", "lugar": "Oficinas del cliente",
            "estado": estado, "notas": "Dato de ejemplo",
        })

    checklist = [{"item": i, "ok": False} for i in CHECKLIST_DEFAULT]
    client.collection("visitas_mercadeo").document().set({
        "vendedor_id": maria, "punto_venta": "Librería Central", "direccion": "6a avenida, Zona 1",
        "fecha": str(today), "checklist": checklist, "pendientes": "Revisar exhibición de vitrina",
        "estado": "Pendiente", "notas": "Dato de ejemplo",
    })

    client.collection("reclamos").document().set({
        "cliente": "Editorial Horizonte", "nit": "9988776-5", "numero_orden": "ORD-4521",
        "fecha_reclamo": str(today - timedelta(days=4)), "fecha_solucion": None,
        "estatus": "En proceso", "descripcion": "Diferencia de color en impresión offset", "vendedor_id": carlos,
    })

    for vendedor_id, planta, linea, monto in [
        (juan, "Offset", "Volantes", 3200.0),
        (juan, "Digital", "Tarjetas de presentación", 950.0),
        (maria, "Valloy", "Etiquetas", 1800.0),
        (carlos, "Colorado", "Empaques", 4200.0),
        (carlos, "Offset", "Revistas", 6100.0),
    ]:
        client.collection("ventas").document().set({
            "vendedor_id": vendedor_id, "fecha": str(today), "planta": planta,
            "linea_venta": linea, "monto": monto, "notas": "Dato de ejemplo",
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


def list_vendedores(solo_activos=True):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("usuarios").where("rol", "==", "vendedor").stream()]
    if solo_activos:
        rows = [r for r in rows if r["activo"]]
    rows.sort(key=lambda r: r["nombre"])
    return rows


def list_productos_interes(solo_activos=True):
    """Catálogo de productos que un vendedor puede marcar como 'productos de
    interés' al registrar un prospecto (Prospección) o una llamada
    (Llamadas) — es la misma lista compartida entre las dos pestañas.
    Cualquier administrador puede agregar productos nuevos desde ahí."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("productos_interes").stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def create_producto_interes(nombre):
    """Devuelve None si se creó bien, o un mensaje de error si el producto
    ya existe en la lista (sin importar mayúsculas/minúsculas)."""
    nombre = (nombre or "").strip()
    if not nombre:
        return "Escribe el nombre del producto."
    existentes = {p["nombre"].strip().lower() for p in list_productos_interes(solo_activos=False)}
    if nombre.lower() in existentes:
        return "Ese producto ya está en la lista."
    get_client().collection("productos_interes").document().set({
        "nombre": nombre, "activo": True,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return None


def delete_producto_interes(producto_id):
    get_client().collection("productos_interes").document(producto_id).delete()


def list_logistica_vendedores(solo_activos=True):
    """Vendedores adicionales, sin usuario propio, que se pueden elegir como
    'vendedor que hizo la venta' en un pedido de Logística (ver
    LOGISTICA_VENDEDORES_INICIAL en config.py). Se combinan con
    list_vendedores() en la pestaña de Logística."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("logistica_vendedores").stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def create_logistica_vendedor(nombre):
    get_client().collection("logistica_vendedores").document().set({
        "nombre": nombre.strip(), "activo": True,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def set_logistica_vendedor_activo(vendedor_id, activo):
    get_client().collection("logistica_vendedores").document(vendedor_id).update({"activo": bool(activo)})


def delete_logistica_vendedor(vendedor_id):
    get_client().collection("logistica_vendedores").document(vendedor_id).delete()


def list_repartidores(solo_activos=True):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("usuarios").where("rol", "==", "repartidor").stream()]
    if solo_activos:
        rows = [r for r in rows if r["activo"]]
    rows.sort(key=lambda r: r["nombre"])
    return rows


_PAGINAS_ROL_CONFIG_DOC_ID = "por_rol"


def get_paginas_por_rol():
    """Devuelve qué pestañas ve CADA ROL por defecto — dict {rol: [keys]} —
    editable desde Administración de usuarios → '🧩 Accesos por rol', sin
    tocar código. Si todavía no se ha guardado nada ahí (o solo se guardó
    para algunos roles), completa con el valor de fábrica
    (config.PAGINAS_BASE_POR_ROL) — mismo patrón que get_nps_preguntas /
    get_margenes_cotizador_digital."""
    from config import PAGINAS_BASE_POR_ROL
    client = get_client()
    snap = client.collection("config_paginas").document(_PAGINAS_ROL_CONFIG_DOC_ID).get()
    data = _doc_to_dict(snap) if snap.exists else None
    guardado = (data or {}).get("por_rol") or {}
    return {**PAGINAS_BASE_POR_ROL, **guardado}


def set_paginas_rol(rol, paginas):
    """Guarda la lista completa de pestañas por defecto para UN rol
    (reemplaza solo lo de ese rol — el resto de roles no se toca)."""
    client = get_client()
    doc_ref = client.collection("config_paginas").document(_PAGINAS_ROL_CONFIG_DOC_ID)
    snap = doc_ref.get()
    actual = dict((_doc_to_dict(snap) or {}).get("por_rol") or {}) if snap.exists else {}
    actual[rol] = list(paginas)
    doc_ref.set({"por_rol": actual, "actualizado_en": datetime.now().isoformat(timespec="seconds")})


def create_usuario(nombre, username, password, rol, tienda=None, paginas_extra=None, paginas_removidas=None):
    """'paginas_extra': claves de config.PAGINAS_REGISTRO a las que este
    usuario tiene acceso ADEMÁS de lo que le da su rol. 'paginas_removidas':
    claves que se le QUITAN aunque su rol normalmente las incluya. Ambas se
    gestionan juntas desde Administración de usuarios → '🔐 Accesos de este
    usuario' (ver también get_paginas_por_rol para los valores por rol)."""
    client = get_client()
    client.collection("usuarios").document().set({
        "nombre": nombre, "username": username, "password_hash": hash_password(password),
        "rol": rol, "activo": True, "fecha_creacion": str(date.today()), "tienda": tienda,
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
    """Elimina el usuario por completo. Los registros que ya haya creado
    (prospectos, citas, ventas, etc.) NO se borran — solo dejan de tener un
    vendedor asignado (se mostrarán con '—')."""
    get_client().collection("usuarios").document(user_id).delete()


def nombre_vendedor(vendedor_id, vendedores=None):
    if vendedor_id is None:
        return "—"
    if vendedores is None:
        vendedores = list_usuarios()
    for v in vendedores:
        if v["id"] == vendedor_id:
            return v["nombre"]
    return "—"


# ---------------------------------------------------------------------------
# Sesiones "recuérdame" — para que, una vez que alguien inicia sesión, la
# plataforma no lo vuelva a sacar hasta que él mismo cierre sesión (incluso
# si la app se reinicia por un nuevo despliegue, o el navegador se cierra).
# Se guarda un token al azar (nunca la contraseña) en una cookie del
# navegador; aquí solo se guarda el HASH de ese token — igual que con las
# contraseñas, para que aunque alguien vea la base de datos no pueda armar
# una cookie válida a partir de lo guardado.
# ---------------------------------------------------------------------------
SESION_RECORDAR_DIAS = 30


def _hash_token_sesion(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_sesion_recordada(user_id):
    """Crea un nuevo token de 'recuérdame' para este usuario y lo guarda (ya
    hasheado) en la base de datos. Devuelve el token SIN hashear — ese es el
    que se guarda en la cookie del navegador, nunca el hash."""
    token = secrets.token_urlsafe(32)
    expira = datetime.now() + timedelta(days=SESION_RECORDAR_DIAS)
    get_client().collection("sesiones_recordadas").document().set({
        "token_hash": _hash_token_sesion(token), "usuario_id": user_id,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
        "expira_en": expira.isoformat(timespec="seconds"),
    })
    return token


def usuario_desde_token_sesion(token):
    """Devuelve el usuario dueño de este token de 'recuérdame' guardado en su
    cookie — solo si el token existe, no ha expirado y el usuario sigue
    activo. None en cualquier otro caso (obliga a iniciar sesión de nuevo)."""
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
    """Invalida un token de 'recuérdame' — se usa al cerrar sesión, para que
    la cookie que quede en ese navegador ya no sirva para volver a entrar."""
    if not token:
        return
    client = get_client()
    for s in client.collection("sesiones_recordadas").where("token_hash", "==", _hash_token_sesion(token)).stream():
        client.collection("sesiones_recordadas").document(s.id).delete()


# ---------------------------------------------------------------------------
# Prospectos / CRM
# ---------------------------------------------------------------------------
def find_prospectos_by_nit(nit, exclude_id=None):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("prospectos").where("nit", "==", nit.strip()).stream()]
    if exclude_id:
        rows = [r for r in rows if r["id"] != exclude_id]
    return rows


def list_prospectos(vendedor_id=None):
    client = get_client()
    coll = client.collection("prospectos")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r["fecha_registro"] or "", reverse=True)
    return rows


def create_prospecto(nombre_cliente, telefono, email, direccion, vendedor_id,
                      fecha_seguimiento, recordatorio, notas, estado, productos=None):
    """Devuelve el id del prospecto recién creado (por ejemplo, lo usa el
    Cotizador Digital para poder ligar automáticamente una cotización a un
    cliente escrito a mano que todavía no existía en Prospección)."""
    doc_ref = get_client().collection("prospectos").document()
    doc_ref.set({
        "nombre_cliente": nombre_cliente, "telefono": telefono, "email": email,
        "direccion": direccion, "vendedor_id": vendedor_id, "fecha_registro": str(date.today()),
        "fecha_seguimiento": str(fecha_seguimiento) if fecha_seguimiento else None,
        "recordatorio": recordatorio, "notas": notas, "estado": estado, "productos": productos or [],
    })
    return doc_ref.id


def update_prospecto(prospecto_id, **kwargs):
    if kwargs:
        get_client().collection("prospectos").document(prospecto_id).update(kwargs)


def get_prospecto(prospecto_id):
    snap = get_client().collection("prospectos").document(prospecto_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def delete_prospecto(prospecto_id):
    """Elimina el prospecto por completo. Citas, cotizaciones u otros registros
    que lo mencionen no se borran, solo dejan de estar vinculados a él."""
    get_client().collection("prospectos").document(prospecto_id).delete()


def prospectos_con_seguimiento_proximo(vendedor_id=None, dias=3):
    hoy = date.today()
    limite = hoy + timedelta(days=dias)
    rows = list_prospectos(vendedor_id)
    return [
        r for r in rows
        if r["fecha_seguimiento"] and hoy.isoformat() <= r["fecha_seguimiento"] <= limite.isoformat()
        and r["estado"] not in ("Cliente (Ganado)", "Perdido")
    ]


# ---------------------------------------------------------------------------
# Registros CF (Consumidor Final) — registros adicionales de facturación
# dentro de un mismo prospecto. Un prospecto puede tener una cantidad
# ilimitada de estos registros (por ejemplo, distintas razones sociales o
# ventas facturadas a "Consumidor Final" asociadas al mismo cliente).
# ---------------------------------------------------------------------------
def list_registros_cf(prospecto_id):
    client = get_client()
    rows = [
        _doc_to_dict(s) for s in client.collection("registros_cf")
        .where("prospecto_id", "==", prospecto_id).stream()
    ]
    rows.sort(key=lambda r: r.get("fecha_registro") or "", reverse=True)
    return rows


def create_registro_cf(prospecto_id, nombre_cliente, nit_cf, telefono, email, direccion):
    get_client().collection("registros_cf").document().set({
        "prospecto_id": prospecto_id, "nombre_cliente": nombre_cliente, "nit_cf": nit_cf.strip(),
        "telefono": telefono, "email": email, "direccion": direccion,
        "fecha_registro": str(date.today()),
    })


def delete_registro_cf(registro_id):
    """Elimina un registro CF por completo (no se puede deshacer)."""
    get_client().collection("registros_cf").document(registro_id).delete()


# ---------------------------------------------------------------------------
# Llamadas
# ---------------------------------------------------------------------------
def find_llamadas_by_nit(nit, exclude_id=None):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("llamadas").where("nit", "==", nit.strip()).stream()]
    if exclude_id:
        rows = [r for r in rows if r["id"] != exclude_id]
    return rows


def list_llamadas(vendedor_id=None):
    client = get_client()
    coll = client.collection("llamadas")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r["fecha_registro"] or "", reverse=True)
    return rows


def create_llamada(nombre_cliente, telefono, email, direccion, vendedor_id,
                    fecha_seguimiento, recordatorio, notas, estado, tipo_llamada, productos=None):
    get_client().collection("llamadas").document().set({
        "nombre_cliente": nombre_cliente, "telefono": telefono, "email": email,
        "direccion": direccion, "vendedor_id": vendedor_id, "fecha_registro": str(date.today()),
        "fecha_seguimiento": str(fecha_seguimiento) if fecha_seguimiento else None,
        "recordatorio": recordatorio, "notas": notas, "estado": estado, "tipo_llamada": tipo_llamada,
        "productos": productos or [],
    })


def update_llamada(llamada_id, **kwargs):
    if kwargs:
        get_client().collection("llamadas").document(llamada_id).update(kwargs)


def get_llamada(llamada_id):
    snap = get_client().collection("llamadas").document(llamada_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def delete_llamada(llamada_id):
    """Elimina la llamada por completo (no se puede deshacer)."""
    get_client().collection("llamadas").document(llamada_id).delete()


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
def list_cotizaciones(vendedor_id=None):
    client = get_client()
    coll = client.collection("cotizaciones")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    for r in rows:
        p = get_prospecto(r["prospecto_id"]) if r.get("prospecto_id") else None
        r["nombre_cliente"] = p["nombre_cliente"] if p else None
        r["nit"] = p.get("nit") if p else None
    rows.sort(key=lambda r: r["fecha_cotizacion"] or "", reverse=True)
    return rows


def create_cotizacion(prospecto_id, vendedor_id, fecha_contacto, fecha_cotizacion,
                       numero_cotizacion, monto, estado, notas):
    get_client().collection("cotizaciones").document().set({
        "prospecto_id": prospecto_id, "vendedor_id": vendedor_id,
        "fecha_contacto": str(fecha_contacto) if fecha_contacto else None,
        "fecha_cotizacion": str(fecha_cotizacion) if fecha_cotizacion else None,
        "numero_cotizacion": numero_cotizacion, "monto": monto, "estado": estado, "notas": notas,
    })


def update_cotizacion(cotizacion_id, **kwargs):
    if kwargs:
        get_client().collection("cotizaciones").document(cotizacion_id).update(kwargs)


def delete_cotizacion(cotizacion_id):
    get_client().collection("cotizaciones").document(cotizacion_id).delete()


# ---------------------------------------------------------------------------
# Citas
# ---------------------------------------------------------------------------
def list_citas(vendedor_id=None, desde=None, hasta=None):
    client = get_client()
    coll = client.collection("citas")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    if desde:
        rows = [r for r in rows if r["fecha"] >= str(desde)]
    if hasta:
        rows = [r for r in rows if r["fecha"] <= str(hasta)]
    rows.sort(key=lambda r: (r["fecha"], r["hora"] or ""))
    return rows


def create_cita(vendedor_id, prospecto_id, cliente_nombre, tipo, fecha, hora, lugar, estado, notas):
    get_client().collection("citas").document().set({
        "vendedor_id": vendedor_id, "prospecto_id": prospecto_id, "cliente_nombre": cliente_nombre,
        "tipo": tipo, "fecha": str(fecha), "hora": str(hora) if hora else None,
        "lugar": lugar, "estado": estado, "notas": notas,
    })


def update_cita(cita_id, **kwargs):
    if kwargs:
        get_client().collection("citas").document(cita_id).update(kwargs)


def delete_cita(cita_id):
    get_client().collection("citas").document(cita_id).delete()


# ---------------------------------------------------------------------------
# Visitas de mercadeo
# ---------------------------------------------------------------------------
def list_visitas_mercadeo(vendedor_id=None):
    client = get_client()
    coll = client.collection("visitas_mercadeo")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    for r in rows:
        r["checklist_items"] = r.get("checklist") or []
    rows.sort(key=lambda r: r["fecha"] or "", reverse=True)
    return rows


def create_visita_mercadeo(vendedor_id, punto_venta, direccion, fecha, checklist_items, pendientes, estado, notas):
    get_client().collection("visitas_mercadeo").document().set({
        "vendedor_id": vendedor_id, "punto_venta": punto_venta, "direccion": direccion,
        "fecha": str(fecha), "checklist": checklist_items, "pendientes": pendientes,
        "estado": estado, "notas": notas,
    })


def update_visita_mercadeo(visita_id, **kwargs):
    if "checklist_items" in kwargs:
        kwargs["checklist"] = kwargs.pop("checklist_items")
    if kwargs:
        get_client().collection("visitas_mercadeo").document(visita_id).update(kwargs)


def delete_visita_mercadeo(visita_id):
    get_client().collection("visitas_mercadeo").document(visita_id).delete()


# ---------------------------------------------------------------------------
# Pendientes de mercadeo
# ---------------------------------------------------------------------------
def list_pendientes_mercadeo(vendedor_id=None):
    client = get_client()
    coll = client.collection("pendientes_mercadeo")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r["fecha_reportada"] or "", reverse=True)
    return rows


def create_pendiente_mercadeo(vendedor_id, tienda, fecha_reportada, pendiente, estado):
    get_client().collection("pendientes_mercadeo").document().set({
        "vendedor_id": vendedor_id, "tienda": tienda,
        "fecha_reportada": str(fecha_reportada) if fecha_reportada else None,
        "pendiente": pendiente, "fecha_finalizacion": None, "estado": estado,
    })


def update_pendiente_mercadeo(pendiente_id, **kwargs):
    if kwargs:
        get_client().collection("pendientes_mercadeo").document(pendiente_id).update(kwargs)


def delete_pendiente_mercadeo(pendiente_id):
    get_client().collection("pendientes_mercadeo").document(pendiente_id).delete()


# ---------------------------------------------------------------------------
# Reclamos
# ---------------------------------------------------------------------------
def list_reclamos(vendedor_id=None):
    client = get_client()
    coll = client.collection("reclamos")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r["fecha_reclamo"] or "", reverse=True)
    return rows


def create_reclamo(cliente, nit, numero_orden, fecha_reclamo, estatus, descripcion, vendedor_id):
    get_client().collection("reclamos").document().set({
        "cliente": cliente, "nit": nit, "numero_orden": numero_orden,
        "fecha_reclamo": str(fecha_reclamo), "fecha_solucion": None,
        "estatus": estatus, "descripcion": descripcion, "vendedor_id": vendedor_id,
        "comentarios_jefe_planta": None, "fecha_cierre": None,
    })


def update_reclamo(reclamo_id, **kwargs):
    if kwargs:
        get_client().collection("reclamos").document(reclamo_id).update(kwargs)


def delete_reclamo(reclamo_id):
    get_client().collection("reclamos").document(reclamo_id).delete()


# ---------------------------------------------------------------------------
# Ventas
# ---------------------------------------------------------------------------
def list_ventas(vendedor_id=None, desde=None, hasta=None):
    client = get_client()
    coll = client.collection("ventas")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    if desde:
        rows = [r for r in rows if r["fecha"] >= str(desde)]
    if hasta:
        rows = [r for r in rows if r["fecha"] <= str(hasta)]
    rows.sort(key=lambda r: r["fecha"], reverse=True)
    return rows


def create_venta(vendedor_id, fecha, planta, linea_venta, monto, notas, cliente=None, numero_ordenes=0):
    get_client().collection("ventas").document().set({
        "vendedor_id": vendedor_id, "fecha": str(fecha), "planta": planta,
        "linea_venta": linea_venta, "monto": monto, "notas": notas,
        "cliente": cliente, "numero_ordenes": numero_ordenes,
    })


def update_venta(venta_id, **kwargs):
    if kwargs:
        get_client().collection("ventas").document(venta_id).update(kwargs)


def delete_venta(venta_id):
    get_client().collection("ventas").document(venta_id).delete()


# ---------------------------------------------------------------------------
# Venta mensual por planta (monto acumulado del mes, por vendedor — lo
# digita manualmente el administrador, no se calcula de las ventas diarias)
# ---------------------------------------------------------------------------
def get_ventas_mensuales_planta(anio_mes):
    """Retorna {vendedor_id: {"vendedor_id", "anio_mes", "montos": {planta: monto}, ...}}
    para el mes indicado (formato 'YYYY-MM')."""
    client = get_client()
    rows = [
        _doc_to_dict(s)
        for s in client.collection("ventas_mensuales_planta").where("anio_mes", "==", anio_mes).stream()
    ]
    return {r["vendedor_id"]: r for r in rows}


def upsert_venta_mensual_planta(vendedor_id, anio_mes, montos):
    """montos: dict {planta: monto}, ej. {"Offset": 1000, "Digital": 500, "Valloy": 0, "Colorado": 200}.
    Si ya existe un registro para ese vendedor y mes, lo reemplaza; si no, lo crea."""
    client = get_client()
    existentes = list(
        client.collection("ventas_mensuales_planta")
        .where("vendedor_id", "==", vendedor_id)
        .where("anio_mes", "==", anio_mes)
        .stream()
    )
    data = {
        "vendedor_id": vendedor_id, "anio_mes": anio_mes, "montos": montos,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    if existentes:
        client.collection("ventas_mensuales_planta").document(existentes[0].id).set(data)
    else:
        client.collection("ventas_mensuales_planta").document().set(data)


# ---------------------------------------------------------------------------
# Utilidad mensual por planta — mismo concepto que la venta mensual de
# arriba (monto acumulado del mes, por vendedor, que digita manualmente el
# administrador), pero para la utilidad/ganancia en vez de la venta.
# ---------------------------------------------------------------------------
def get_utilidades_mensuales_planta(anio_mes):
    """Retorna {vendedor_id: {"vendedor_id", "anio_mes", "montos": {planta: monto}, ...}}
    para el mes indicado (formato 'YYYY-MM')."""
    client = get_client()
    rows = [
        _doc_to_dict(s)
        for s in client.collection("utilidades_mensuales_planta").where("anio_mes", "==", anio_mes).stream()
    ]
    return {r["vendedor_id"]: r for r in rows}


def upsert_utilidad_mensual_planta(vendedor_id, anio_mes, montos):
    """montos: dict {planta: monto}, ej. {"Offset": 1000, "Digital": 500, "Valloy": 0, "Colorado": 200}.
    Si ya existe un registro para ese vendedor y mes, lo reemplaza; si no, lo crea."""
    client = get_client()
    existentes = list(
        client.collection("utilidades_mensuales_planta")
        .where("vendedor_id", "==", vendedor_id)
        .where("anio_mes", "==", anio_mes)
        .stream()
    )
    data = {
        "vendedor_id": vendedor_id, "anio_mes": anio_mes, "montos": montos,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    if existentes:
        client.collection("utilidades_mensuales_planta").document(existentes[0].id).set(data)
    else:
        client.collection("utilidades_mensuales_planta").document().set(data)


# ---------------------------------------------------------------------------
# Proyección mensual por planta — mismo concepto que la venta/utilidad
# mensual de arriba (monto acumulado del mes, por vendedor, que digita
# manualmente el administrador), pero para la proyección/meta de venta del
# mes en vez de la venta real. Colección totalmente aparte, así que nunca se
# mezcla con los datos reales de 'Ventas'.
# ---------------------------------------------------------------------------
def get_proyecciones_mensuales_planta(anio_mes):
    """Retorna {vendedor_id: {"vendedor_id", "anio_mes", "montos": {planta: monto}, ...}}
    para el mes indicado (formato 'YYYY-MM')."""
    client = get_client()
    rows = [
        _doc_to_dict(s)
        for s in client.collection("proyecciones_mensuales_planta").where("anio_mes", "==", anio_mes).stream()
    ]
    return {r["vendedor_id"]: r for r in rows}


def upsert_proyeccion_mensual_planta(vendedor_id, anio_mes, montos):
    """montos: dict {planta: monto}, ej. {"Offset": 1000, "Digital": 500, "Valloy": 0, "Colorado": 200}.
    Si ya existe un registro para ese vendedor y mes, lo reemplaza; si no, lo crea."""
    client = get_client()
    existentes = list(
        client.collection("proyecciones_mensuales_planta")
        .where("vendedor_id", "==", vendedor_id)
        .where("anio_mes", "==", anio_mes)
        .stream()
    )
    data = {
        "vendedor_id": vendedor_id, "anio_mes": anio_mes, "montos": montos,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    if existentes:
        client.collection("proyecciones_mensuales_planta").document(existentes[0].id).set(data)
    else:
        client.collection("proyecciones_mensuales_planta").document().set(data)


# ---------------------------------------------------------------------------
# Diseño Gráfico (tablero estilo Trello)
# ---------------------------------------------------------------------------
def list_disenos(vendedor_id=None):
    """Retorna las solicitudes de diseño, más nuevas primero."""
    client = get_client()
    coll = client.collection("disenos")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_diseno(diseno_id):
    snap = get_client().collection("disenos").document(diseno_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_diseno(
    vendedor_id, cliente, producto, material, acabado, medida, fecha_necesaria, estado,
    archivos=None, cambios_necesarios=None,
):
    """archivos: lista de hasta 3 dicts {"nombre", "tipo", "b64"}."""
    get_client().collection("disenos").document().set({
        "vendedor_id": vendedor_id, "cliente": cliente, "producto": producto,
        "material": material, "acabado": acabado, "medida": medida,
        "fecha_necesaria": str(fecha_necesaria) if fecha_necesaria else None,
        "estado": estado, "creado_en": datetime.now().isoformat(timespec="seconds"),
        "archivos": archivos or [],
        "cambios_necesarios": cambios_necesarios, "detenido_emergencia": False,
        # Hora exacta en la que la solicitud llegó por primera vez a
        # 'Entregado' — se llena sola (ver update_diseno) para poder medir
        # cuánto tiempo pasa desde que ingresa hasta que se entrega.
        "fecha_entregado": None,
    })


def update_diseno(diseno_id, **kwargs):
    """Si estos cambios incluyen mover la solicitud a 'Entregado' por primera
    vez, registra la hora exacta en 'fecha_entregado' (mismo reloj que
    'creado_en', para que el tiempo transcurrido se calcule bien) — así se
    puede medir cuánto tarda cada solicitud desde que ingresa hasta que se
    entrega. Si ya tenía fecha_entregado (por ejemplo, se movió hacia atrás y
    volvió a 'Entregado'), no la vuelve a pisar."""
    if not kwargs:
        return
    if kwargs.get("estado") == "Entregado":
        actual = get_diseno(diseno_id) or {}
        if actual.get("estado") != "Entregado" and not actual.get("fecha_entregado"):
            kwargs = dict(kwargs)
            kwargs["fecha_entregado"] = datetime.now().isoformat(timespec="seconds")
    get_client().collection("disenos").document(diseno_id).update(kwargs)


def delete_diseno(diseno_id):
    d = get_diseno(diseno_id)
    if d:
        eliminar_archivos_storage(d.get("archivos"))
    get_client().collection("disenos").document(diseno_id).delete()


# ---------------------------------------------------------------------------
# Diseño Gráfico — Álvaro (tablero independiente, mismo sistema que el de
# Nicolás pero con su propia colección, para que las solicitudes no se mezclen)
# ---------------------------------------------------------------------------
def list_disenos_alvaro(vendedor_id=None):
    """Retorna las solicitudes de diseño de Álvaro, más nuevas primero."""
    client = get_client()
    coll = client.collection("disenos_alvaro")
    query = coll.where("vendedor_id", "==", vendedor_id) if vendedor_id else coll
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_diseno_alvaro(diseno_id):
    snap = get_client().collection("disenos_alvaro").document(diseno_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_diseno_alvaro(
    vendedor_id, cliente, producto, material, acabado, medida, fecha_necesaria, estado,
    archivos=None, cambios_necesarios=None,
):
    """archivos: lista de hasta 3 dicts {"nombre", "tipo", "b64"}."""
    get_client().collection("disenos_alvaro").document().set({
        "vendedor_id": vendedor_id, "cliente": cliente, "producto": producto,
        "material": material, "acabado": acabado, "medida": medida,
        "fecha_necesaria": str(fecha_necesaria) if fecha_necesaria else None,
        "estado": estado, "creado_en": datetime.now().isoformat(timespec="seconds"),
        "archivos": archivos or [],
        "cambios_necesarios": cambios_necesarios, "detenido_emergencia": False,
        # Hora exacta en la que la solicitud llegó por primera vez a
        # 'Entregado' — se llena sola (ver update_diseno_alvaro) para poder
        # medir cuánto tiempo pasa desde que ingresa hasta que se entrega.
        "fecha_entregado": None,
    })


def update_diseno_alvaro(diseno_id, **kwargs):
    """Mismo concepto que update_diseno, para el tablero de Álvaro."""
    if not kwargs:
        return
    if kwargs.get("estado") == "Entregado":
        actual = get_diseno_alvaro(diseno_id) or {}
        if actual.get("estado") != "Entregado" and not actual.get("fecha_entregado"):
            kwargs = dict(kwargs)
            kwargs["fecha_entregado"] = datetime.now().isoformat(timespec="seconds")
    get_client().collection("disenos_alvaro").document(diseno_id).update(kwargs)


def delete_diseno_alvaro(diseno_id):
    d = get_diseno_alvaro(diseno_id)
    if d:
        eliminar_archivos_storage(d.get("archivos"))
    get_client().collection("disenos_alvaro").document(diseno_id).delete()


# ---------------------------------------------------------------------------
# Logística (pedidos AM/PM de la ruta de reparto)
# ---------------------------------------------------------------------------
def list_pedidos(fecha=None, franja=None, repartidor_id=None, vendedor_id=None):
    client = get_client()
    query = client.collection("pedidos")
    if fecha:
        query = query.where("fecha", "==", str(fecha))
    if franja:
        query = query.where("franja", "==", franja)
    if repartidor_id:
        query = query.where("repartidor_id", "==", repartidor_id)
    if vendedor_id:
        query = query.where("vendedor_id", "==", vendedor_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_pedido(pedido_id):
    snap = get_client().collection("pedidos").document(pedido_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def _siguiente_numero_envio():
    """Numeración corrida (no reinicia por día), empezando en 1 — el 'ENVÍO
    No.' que aparece impreso en el PDF de cada pedido, igual que la libreta
    física de envíos que se usaba en papel."""
    rows = [_doc_to_dict(s) for s in get_client().collection("pedidos").stream()]
    numeros = [r.get("numero_envio") for r in rows if isinstance(r.get("numero_envio"), int)]
    return (max(numeros, default=0)) + 1


def create_pedido(
    fecha, franja, cliente, direccion, zona, producto, numero_orden,
    vendedor_id, repartidor_id, notas=None, tipo_ruta=None, atencion_a=None, productos=None,
):
    get_client().collection("pedidos").document().set({
        "fecha": str(fecha), "franja": franja, "cliente": cliente, "direccion": direccion,
        "zona": zona, "producto": producto, "numero_orden": numero_orden,
        "vendedor_id": vendedor_id, "repartidor_id": repartidor_id,
        "estado": "Pendiente", "notas": notas, "tipo_ruta": tipo_ruta,
        "atencion_a": atencion_a, "productos": productos or [],
        "numero_envio": _siguiente_numero_envio(),
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_pedido(pedido_id, **kwargs):
    if kwargs:
        get_client().collection("pedidos").document(pedido_id).update(kwargs)


def delete_pedido(pedido_id):
    get_client().collection("pedidos").document(pedido_id).delete()


# ---------------------------------------------------------------------------
# Rutas extra de Logística: Compras, Trámites y Papelería — versión sencilla
# de "pedido" (sin cliente/zona/franja/productos), usada para mandados del
# repartidor que no son un envío de mercadería. Las 3 comparten la misma
# colección ("rutas_extra"), diferenciadas por el campo "tipo".
# ---------------------------------------------------------------------------
def list_rutas_extra(tipo=None, repartidor_id=None):
    client = get_client()
    query = client.collection("rutas_extra")
    if tipo:
        query = query.where("tipo", "==", tipo)
    if repartidor_id:
        query = query.where("repartidor_id", "==", repartidor_id)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: r.get("fecha") or "", reverse=True)
    return rows


def get_ruta_extra(ruta_id):
    snap = get_client().collection("rutas_extra").document(ruta_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_ruta_extra(tipo, fecha, empresa, descripcion, repartidor_id):
    get_client().collection("rutas_extra").document().set({
        "tipo": tipo, "fecha": str(fecha), "empresa": empresa, "descripcion": descripcion,
        "repartidor_id": repartidor_id, "estado": "Pendiente",
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_ruta_extra(ruta_id, **kwargs):
    if kwargs:
        get_client().collection("rutas_extra").document(ruta_id).update(kwargs)


def delete_ruta_extra(ruta_id):
    get_client().collection("rutas_extra").document(ruta_id).delete()


# ---------------------------------------------------------------------------
# Capacitación — personal por tienda
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


def set_personal_tienda_activo(persona_id, activo):
    get_client().collection("personal_tiendas").document(persona_id).update({"activo": bool(activo)})


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
    la reemplaza; si no, la crea. 'horas' son las horas de capacitación que
    recibió la persona para esta calificación, y 'fecha' es la fecha en que
    se dio esa capacitación/examen (distinta de 'actualizado_en', que es
    cuándo se guardó en el sistema)."""
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
# se va a impartir cada módulo/submódulo, a qué tienda y quién la da. Es
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
    asistencias que la gente ya haya confirmado para ella (ya no tiene
    sentido conservarlas sin la programación a la que pertenecen)."""
    client = get_client()
    for a in list_capacitacion_asistencias(programacion_id=programacion_id):
        client.collection("capacitacion_asistencias").document(a["id"]).delete()
    client.collection("capacitacion_programaciones").document(programacion_id).delete()


# ---------------------------------------------------------------------------
# Capacitación — asistencias: registro de quién confirmó su asistencia a una
# capacitación programada (vía el formulario público que se abre al escanear
# el QR de esa programación). Queda ligada tanto a la programación como al
# módulo/submódulo, para poder verla desde el expediente del submódulo (o del
# módulo, si la capacitación era general, sin submódulo específico).
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
    """Registra la asistencia de una persona a una capacitación programada,
    a partir del formulario público del QR. Copia el módulo/submódulo/fecha
    de la programación al momento de confirmar, para que la asistencia se
    pueda consultar sin tener que ir a buscar la programación cada vez."""
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
    NO cambia la fecha original — así el diploma se puede volver a descargar
    después con la misma fecha de finalización."""
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
# Sistema de Tickets — Tiendas (fila de clientes nuevos, con check-in público
# por QR desde el celular del cliente — no requiere haber iniciado sesión).
# Se mide el tiempo en cada etapa guardando la hora exacta en la que el
# ticket entra a ella: hora_ingreso (check-in), hora_inicio_atencion,
# hora_inicio_elaboracion y hora_facturado.
# ---------------------------------------------------------------------------
_TICKET_TS_POR_ESTADO = {
    "En atención": "hora_inicio_atencion",
    "En elaboración": "hora_inicio_elaboracion",
    "Facturado": "hora_facturado",
    "Abandono": "hora_abandono",
}

# Guatemala usa siempre UTC-6 (no tiene horario de verano), así que un
# desplazamiento fijo es suficiente y no depende de que el servidor donde
# corre Streamlit Cloud tenga instalada la base de datos de zonas horarias.
GUATEMALA_TZ = timezone(timedelta(hours=-6))


def ahora_guatemala():
    """Hora actual en horario de Guatemala, como datetime 'naive' (sin
    información de zona horaria en el valor) para que se guarde y se compare
    siempre igual, sin importar en qué servidor/zona horaria esté corriendo
    la app. Se usa para todo lo relacionado al Sistema de Tickets — Tiendas."""
    return datetime.now(GUATEMALA_TZ).replace(tzinfo=None)


def hoy_guatemala():
    return ahora_guatemala().date()


def _siguiente_numero_ticket(tienda):
    """Numeración diaria por tienda: reinicia en 1 cada día (día de Guatemala)."""
    hoy = str(hoy_guatemala())
    tickets_hoy = [
        t for t in list_tickets_tienda(tienda=tienda) if t.get("fecha") == hoy
    ]
    return (max([t.get("numero_ticket") or 0 for t in tickets_hoy], default=0)) + 1


def create_ticket_tienda(tienda, nombre, telefono, servicio):
    """Crea un ticket nuevo. Esta es la función que usa el formulario público
    de check-in (por QR) — se llama SIN que el cliente haya iniciado sesión.
    'servicio' es una lista (el cliente puede elegir varios productos/servicios
    del catálogo TICKET_SERVICIOS); por compatibilidad también acepta texto
    suelto y lo convierte en una lista de un solo elemento.
    Devuelve el id y el número de ticket asignado, para mostrárselo al cliente."""
    if isinstance(servicio, list):
        servicio_lista = [s for s in servicio if s]
    else:
        servicio_lista = [servicio.strip()] if servicio and servicio.strip() else []
    numero = _siguiente_numero_ticket(tienda)
    doc_ref = get_client().collection("tickets_tienda").document()
    # El ticket entra directo a "En atención" (columna "En espera" del
    # tablero) — ya no existe la etapa intermedia "Esperando"/"Ingresado",
    # así que hora_inicio_atencion queda igual a hora_ingreso.
    ahora = ahora_guatemala().isoformat(timespec="seconds")
    doc_ref.set({
        "tienda": tienda, "fecha": str(hoy_guatemala()), "numero_ticket": numero,
        "nombre": nombre.strip(), "telefono": telefono.strip(), "servicio": servicio_lista,
        "estado": "En atención",
        "hora_ingreso": ahora,
        "hora_inicio_atencion": ahora, "hora_inicio_elaboracion": None, "hora_facturado": None,
        "hora_abandono": None, "motivo_abandono": None, "asesor_id": None,
    })
    return {"id": doc_ref.id, "numero_ticket": numero}


def list_tickets_tienda(tienda=None, fecha=None, activos_solo=False):
    """Tickets 'vivos' (no incluye los que se hayan eliminado — para esos ver
    list_tickets_eliminados)."""
    client = get_client()
    query = client.collection("tickets_tienda")
    if tienda:
        query = query.where("tienda", "==", tienda)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows = [r for r in rows if not r.get("eliminado")]
    if fecha:
        rows = [r for r in rows if r.get("fecha") == fecha]
    if activos_solo:
        rows = [r for r in rows if r.get("estado") not in ("Facturado", "Abandono")]
    rows.sort(key=lambda r: r.get("hora_ingreso") or "", reverse=True)
    return rows


def list_tickets_eliminados(tienda=None):
    """Todos los tickets que se han eliminado (con motivo, quién y cuándo),
    para el listado de auditoría al final de la pestaña de Tickets — Tiendas."""
    client = get_client()
    query = client.collection("tickets_tienda")
    if tienda:
        query = query.where("tienda", "==", tienda)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows = [r for r in rows if r.get("eliminado")]
    rows.sort(key=lambda r: r.get("eliminado_en") or "", reverse=True)
    return rows


def get_ticket_tienda(ticket_id):
    snap = get_client().collection("tickets_tienda").document(ticket_id).get()
    return _doc_to_dict(snap) if snap.exists else None


_SIN_CAMBIO_ASESOR = object()


def avanzar_ticket_tienda(ticket_id, nuevo_estado, asesor_id=_SIN_CAMBIO_ASESOR):
    """Cambia el estado del ticket y, si corresponde, registra la hora exacta
    en la que entró a esa etapa (para poder medir cuánto tiempo pasó en cada
    una: espera, elaboración, etc.). Si se pasa 'asesor_id' (por ejemplo al
    pasar a 'En elaboración'), también queda asignada esa persona (un id de
    "personal_tiendas") al ticket; si no se pasa, la persona ya asignada no
    se toca."""
    cambios = {"estado": nuevo_estado}
    campo_ts = _TICKET_TS_POR_ESTADO.get(nuevo_estado)
    if campo_ts:
        cambios[campo_ts] = ahora_guatemala().isoformat(timespec="seconds")
    if asesor_id is not _SIN_CAMBIO_ASESOR:
        cambios["asesor_id"] = asesor_id
    get_client().collection("tickets_tienda").document(ticket_id).update(cambios)


def abandonar_ticket_tienda(ticket_id, motivo=None):
    """Marca el ticket como 'Abandono' (el cliente no completó su proceso, por
    la razón que sea) y guarda el motivo junto con la hora exacta."""
    get_client().collection("tickets_tienda").document(ticket_id).update({
        "estado": "Abandono",
        "hora_abandono": ahora_guatemala().isoformat(timespec="seconds"),
        "motivo_abandono": (motivo or "").strip() or None,
    })


def eliminar_ticket_tienda(ticket_id, motivo, eliminado_por=None):
    """'Elimina' un ticket del tablero (deja de aparecer ahí y en el
    historial), pero NO lo borra de la base de datos: lo marca como
    eliminado y guarda el motivo, quién lo eliminó y cuándo, para que quede
    un registro de auditoría (ver list_tickets_eliminados)."""
    get_client().collection("tickets_tienda").document(ticket_id).update({
        "eliminado": True,
        "motivo_eliminacion": (motivo or "").strip() or None,
        "eliminado_por": eliminado_por,
        "eliminado_en": ahora_guatemala().isoformat(timespec="seconds"),
    })


def update_ticket_tienda(ticket_id, **kwargs):
    if kwargs:
        get_client().collection("tickets_tienda").document(ticket_id).update(kwargs)


_TICKET_KPI_DEFAULT = {"meta_espera": None, "meta_atencion": None, "meta_elaboracion": None}


def get_ticket_kpis(tienda):
    """Tiempos meta (en minutos) configurados para una tienda, para cada
    etapa del Sistema de Tickets — Tiendas: 'meta_atencion' (En espera, antes
    de pasar a elaboración) y 'meta_elaboracion' (En elaboración, antes de
    facturar). 'meta_espera' ya no se usa (existía para la etapa
    "Ingresado", que se eliminó) — se deja en el registro solo por
    compatibilidad con datos antiguos. Si todavía no se ha configurado nada
    para esa tienda, los valores vienen en None (sin meta) y no se pinta
    nada en rojo."""
    snap = get_client().collection("tickets_kpis_metas").document(tienda).get()
    if not snap.exists:
        return dict(_TICKET_KPI_DEFAULT)
    data = _doc_to_dict(snap)
    return {
        "meta_espera": data.get("meta_espera"),
        "meta_atencion": data.get("meta_atencion"),
        "meta_elaboracion": data.get("meta_elaboracion"),
    }


def set_ticket_kpis(tienda, meta_espera, meta_atencion, meta_elaboracion):
    """Guarda (o corrige) los tiempos meta de una tienda. Cada valor es en
    minutos, o None para dejar esa etapa sin meta."""
    get_client().collection("tickets_kpis_metas").document(tienda).set({
        "tienda": tienda, "meta_espera": meta_espera,
        "meta_atencion": meta_atencion, "meta_elaboracion": meta_elaboracion,
    })


def delete_ticket_tienda(ticket_id):
    """Elimina un ticket de la base de datos por completo y sin dejar
    rastro (no se puede deshacer). No se usa desde la pestaña de Tickets —
    ahí se usa eliminar_ticket_tienda(), que sí deja un registro de
    auditoría; esta función queda disponible para una limpieza manual de
    datos si algún día hace falta."""
    get_client().collection("tickets_tienda").document(ticket_id).delete()


# ---------------------------------------------------------------------------
# Mantenimiento de Maquinaria (por planta): cada máquina/impresora es un
# registro en "maquinas"; sus mantenimientos (preventivos y correctivos) son
# registros en "mantenimientos_maquinas", ligados por "maquina_id".
# ---------------------------------------------------------------------------
def list_maquinas(planta=None, solo_activas=False):
    client = get_client()
    query = client.collection("maquinas")
    if planta:
        query = query.where("planta", "==", planta)
    rows = [_doc_to_dict(s) for s in query.stream()]
    if solo_activas:
        rows = [r for r in rows if r.get("activa", True)]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def get_maquina(maquina_id):
    snap = get_client().collection("maquinas").document(maquina_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_maquina(nombre, tipo_maquina, planta, numero_serie=None, notas=None, codigo_alterno_gasto=None):
    doc_ref = get_client().collection("maquinas").document()
    doc_ref.set({
        "nombre": nombre.strip(), "tipo_maquina": (tipo_maquina or "").strip() or None,
        "planta": planta, "numero_serie": (numero_serie or "").strip() or None,
        "codigo_alterno_gasto": (codigo_alterno_gasto or "").strip() or None,
        "notas": (notas or "").strip() or None, "activa": True,
        "creado_en": ahora_guatemala().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def update_maquina(maquina_id, **kwargs):
    if kwargs:
        get_client().collection("maquinas").document(maquina_id).update(kwargs)


def delete_maquina(maquina_id):
    """Elimina la máquina junto con todo su historial de mantenimientos
    (preventivos y correctivos), para no dejar registros huérfanos."""
    client = get_client()
    for m in list_mantenimientos_maquina(maquina_id):
        client.collection("mantenimientos_maquinas").document(m["id"]).delete()
    client.collection("maquinas").document(maquina_id).delete()


def list_mantenimientos_maquina(maquina_id, tipo=None):
    """Historial de mantenimientos de una máquina (preventivos y
    correctivos juntos, o solo uno de los dos tipos si se especifica
    'tipo'), más recientes primero."""
    client = get_client()
    rows = [
        _doc_to_dict(s)
        for s in client.collection("mantenimientos_maquinas").where("maquina_id", "==", maquina_id).stream()
    ]
    if tipo:
        rows = [r for r in rows if r.get("tipo") == tipo]
    rows.sort(key=lambda r: r.get("fecha") or "", reverse=True)
    return rows


def get_mantenimiento(mantenimiento_id):
    snap = get_client().collection("mantenimientos_maquinas").document(mantenimiento_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def list_mantenimientos_todos():
    """Todos los mantenimientos (preventivos y correctivos) de todas las
    máquinas, sin filtrar por una sola — para los KPIs y alertas generales
    de la pantalla principal de Mantenimiento de Maquinaria."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("mantenimientos_maquinas").stream()]
    rows.sort(key=lambda r: r.get("fecha") or "", reverse=True)
    return rows


def create_mantenimiento(maquina_id, tipo, **campos):
    """Crea un registro de mantenimiento ('Preventivo' o 'Correctivo') para
    una máquina. 'campos' admite: fecha, proveedor, costo, repuesto_cambiado,
    tiempo_garantia, numero_factura, notas, factura_nombre/tipo/b64,
    foto_repuesto_nombre/tipo/b64, realizado (solo aplica a 'Preventivo' —
    si ya se llevó a cabo el mantenimiento programado)."""
    doc_ref = get_client().collection("mantenimientos_maquinas").document()
    data = {
        "maquina_id": maquina_id, "tipo": tipo,
        "creado_en": ahora_guatemala().isoformat(timespec="seconds"),
    }
    data.update(campos)
    doc_ref.set(data)
    return doc_ref.id


def update_mantenimiento(mantenimiento_id, **kwargs):
    if kwargs:
        get_client().collection("mantenimientos_maquinas").document(mantenimiento_id).update(kwargs)


def delete_mantenimiento(mantenimiento_id):
    get_client().collection("mantenimientos_maquinas").document(mantenimiento_id).delete()


# ---------------------------------------------------------------------------
# Cotizador Técnico: catálogo de máquinas y papel (con costos reales, que
# carga el propio Steven — el catálogo empieza vacío, sin datos de ejemplo) y
# cotizaciones técnicas — la ficha de especificación de un trabajo (formato
# de la pieza, tintas, papel, máquina, cantidad) con cálculo automático de
# pliegos, planchas, pasadas de máquina y costo total. Inspirado en el
# enfoque de estimación de sistemas MIS de impresión (ej. Optimus), pero
# construido a la medida de Visión Digital — ver app_pages/19_Cotizador_Tecnico.py.
# ---------------------------------------------------------------------------
def list_tecnico_maquinas(solo_activos=True):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("tecnico_maquinas").stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: r.get("nombre") or "")
    return rows


def get_tecnico_maquina(maquina_id):
    if not maquina_id:
        return None
    snap = get_client().collection("tecnico_maquinas").document(maquina_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_tecnico_maquina(nombre, ancho_max, alto_max, costo_millar_pasadas, costo_plancha):
    get_client().collection("tecnico_maquinas").document().set({
        "nombre": nombre.strip(), "ancho_max": float(ancho_max), "alto_max": float(alto_max),
        "costo_millar_pasadas": float(costo_millar_pasadas), "costo_plancha": float(costo_plancha),
        "activo": True, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_tecnico_maquina(maquina_id, **kwargs):
    if kwargs:
        get_client().collection("tecnico_maquinas").document(maquina_id).update(kwargs)


def delete_tecnico_maquina(maquina_id):
    get_client().collection("tecnico_maquinas").document(maquina_id).delete()


def bulk_upsert_tecnico_maquinas(filas):
    """Carga masiva desde la plantilla de Excel — 'filas' es una lista de
    dicts con nombre/ancho_max/alto_max/costo_millar_pasadas/costo_plancha.
    Si ya existe una máquina con el mismo nombre (sin distinguir mayúsculas),
    se ACTUALIZA en vez de duplicarla — así es seguro volver a subir el mismo
    archivo más adelante para agregar máquinas nuevas. Retorna
    (creadas, actualizadas)."""
    client = get_client()
    existentes = list_tecnico_maquinas(solo_activos=False)
    por_nombre = {(e.get("nombre") or "").strip().lower(): e for e in existentes}
    creadas = actualizadas = 0
    for fila in filas:
        nombre = (fila.get("nombre") or "").strip()
        if not nombre:
            continue
        datos = {
            "nombre": nombre, "ancho_max": float(fila["ancho_max"]), "alto_max": float(fila["alto_max"]),
            "costo_millar_pasadas": float(fila["costo_millar_pasadas"]), "costo_plancha": float(fila["costo_plancha"]),
        }
        existente = por_nombre.get(nombre.lower())
        if existente:
            client.collection("tecnico_maquinas").document(existente["id"]).update(datos)
            actualizadas += 1
        else:
            datos.update({"activo": True, "creado_en": datetime.now().isoformat(timespec="seconds")})
            client.collection("tecnico_maquinas").document().set(datos)
            creadas += 1
    return creadas, actualizadas


def list_tecnico_papeles(solo_activos=True):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("tecnico_papeles").stream()]
    if solo_activos:
        rows = [r for r in rows if r.get("activo", True)]
    rows.sort(key=lambda r: r.get("tipo") or "")
    return rows


def get_tecnico_papel(papel_id):
    if not papel_id:
        return None
    snap = get_client().collection("tecnico_papeles").document(papel_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_tecnico_papel(tipo, fabricante, gramaje, ancho, alto, costo_pliego):
    get_client().collection("tecnico_papeles").document().set({
        "tipo": tipo.strip(), "fabricante": fabricante.strip(), "gramaje": float(gramaje),
        "ancho": float(ancho), "alto": float(alto), "costo_pliego": float(costo_pliego),
        "activo": True, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def update_tecnico_papel(papel_id, **kwargs):
    if kwargs:
        get_client().collection("tecnico_papeles").document(papel_id).update(kwargs)


def delete_tecnico_papel(papel_id):
    get_client().collection("tecnico_papeles").document(papel_id).delete()


def bulk_upsert_tecnico_papeles(filas):
    """Igual que bulk_upsert_tecnico_maquinas, pero para el catálogo de
    papel. Se identifica cada papel por tipo + fabricante + gramaje (sin
    distinguir mayúsculas) — permite tener varios gramajes del mismo tipo y
    fabricante como productos distintos. Retorna (creados, actualizados)."""
    client = get_client()
    existentes = list_tecnico_papeles(solo_activos=False)

    def _llave(tipo, fabricante, gramaje):
        return ((tipo or "").strip().lower(), (fabricante or "").strip().lower(), round(float(gramaje), 2))

    por_llave = {_llave(e.get("tipo"), e.get("fabricante"), e.get("gramaje") or 0): e for e in existentes}
    creados = actualizados = 0
    for fila in filas:
        tipo = (fila.get("tipo") or "").strip()
        if not tipo:
            continue
        datos = {
            "tipo": tipo, "fabricante": (fila.get("fabricante") or "").strip(),
            "gramaje": float(fila["gramaje"]), "ancho": float(fila["ancho"]), "alto": float(fila["alto"]),
            "costo_pliego": float(fila["costo_pliego"]),
        }
        llave = _llave(tipo, fila.get("fabricante"), fila["gramaje"])
        existente = por_llave.get(llave)
        if existente:
            client.collection("tecnico_papeles").document(existente["id"]).update(datos)
            actualizados += 1
        else:
            datos.update({"activo": True, "creado_en": datetime.now().isoformat(timespec="seconds")})
            client.collection("tecnico_papeles").document().set(datos)
            creados += 1
    return creados, actualizados


def _siguiente_numero_tecnico():
    """Numeración corrida (no reinicia por día) para las cotizaciones del
    Cotizador Técnico — ej. TEC-0001, TEC-0002, ..."""
    rows = [_doc_to_dict(s) for s in get_client().collection("tecnico_cotizaciones").stream()]
    numeros = [r.get("numero") for r in rows if isinstance(r.get("numero"), int)]
    return (max(numeros, default=0)) + 1


def list_tecnico_cotizaciones():
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("tecnico_cotizaciones").stream()]
    rows.sort(key=lambda r: r.get("numero") or 0, reverse=True)
    return rows


def get_tecnico_cotizacion(cotizacion_id):
    if not cotizacion_id:
        return None
    snap = get_client().collection("tecnico_cotizaciones").document(cotizacion_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_tecnico_cotizacion(**campos):
    """Crea una cotización técnica. 'campos' admite: cliente, maquina_id,
    maquina_nombre, papel_id, papel_nombre, ancho_pieza, alto_pieza,
    cantidad, tintas_frente, tintas_dorso, merma_pct, piezas_por_pliego,
    pliegos_necesarios, planchas_necesarias, pasadas_maquina, costo_papel,
    costo_planchas, costo_pasadas, acabados (lista de {descripcion, costo}),
    costo_total, margen_pct, precio_venta, utilidad, margen_real_pct,
    estado, notas, creado_por."""
    numero = _siguiente_numero_tecnico()
    doc_ref = get_client().collection("tecnico_cotizaciones").document()
    data = {
        "numero": numero,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    }
    data.update(campos)
    doc_ref.set(data)
    return {"id": doc_ref.id, "numero": numero}


def update_tecnico_cotizacion(cotizacion_id, **kwargs):
    if kwargs:
        get_client().collection("tecnico_cotizaciones").document(cotizacion_id).update(kwargs)


def delete_tecnico_cotizacion(cotizacion_id):
    get_client().collection("tecnico_cotizaciones").document(cotizacion_id).delete()


# ---------------------------------------------------------------------------
# Cotizador Digital: convierte el catálogo de precios LPM Digital en un
# formulario de cotización (ver app_pages/27_Cotizador_Digital.py y
# pricing_data.py). Al crear una cotización aquí también se crea
# automáticamente la fila correspondiente en "Cotizaciones" (colección
# "cotizaciones"), para que quede en el mismo seguimiento comercial que el
# resto — ver create_cotizacion_digital.
# ---------------------------------------------------------------------------
_CD_CONFIG_DOC_ID = "margenes"


def get_margenes_cotizador_digital():
    """Retorna el % de margen de utilidad configurado por tarifa —
    {"normal": .., "urgencia": .., "tienda": .., "gerencial": ..}. Si todavía
    no se ha guardado nada (nunca se tocó la pestaña '⚙️ Márgenes'), retorna
    el valor de fábrica (pricing_data.MARGENES_INICIAL, definido por Steven)
    sin necesidad de sembrarlo antes en la base de datos — mismo patrón que
    get_nps_preguntas."""
    from pricing_data import MARGENES_INICIAL
    client = get_client()
    snap = client.collection("cotizador_digital_config").document(_CD_CONFIG_DOC_ID).get()
    data = _doc_to_dict(snap) if snap.exists else None
    if data and data.get("margenes"):
        # Por si en el futuro se agrega una tarifa nueva a TARIFAS_DIGITAL sin
        # que todavía se haya guardado un valor para ella — se completa con
        # el valor de fábrica en vez de quedar en 0.
        return {**MARGENES_INICIAL, **data["margenes"]}
    return dict(MARGENES_INICIAL)


def set_margenes_cotizador_digital(margenes):
    """Guarda el % de margen de utilidad por tarifa (reemplaza todo lo que
    hubiera guardado antes) — margenes: dict {"normal": .., "urgencia": ..,
    "tienda": .., "gerencial": ..}."""
    client = get_client()
    client.collection("cotizador_digital_config").document(_CD_CONFIG_DOC_ID).set({
        "margenes": {k: float(v) for k, v in margenes.items()},
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def _siguiente_numero_cotizacion_digital():
    """Numeración corrida (no reinicia por día) — CD-0001, CD-0002, ..."""
    rows = [_doc_to_dict(s) for s in get_client().collection("cotizaciones_digital").stream()]
    numeros = [r.get("numero") for r in rows if isinstance(r.get("numero"), int)]
    return (max(numeros, default=0)) + 1


def list_cotizaciones_digital():
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("cotizaciones_digital").stream()]
    rows.sort(key=lambda r: r.get("numero") or 0, reverse=True)
    return rows


def get_cotizacion_digital(cotizacion_id):
    if not cotizacion_id:
        return None
    snap = get_client().collection("cotizaciones_digital").document(cotizacion_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_cotizacion_digital(prospecto_id, vendedor_id, nombre_producto, tipo_trabajo,
                               detalle, resultado, notas, creado_por):
    """Crea la cotización del Cotizador Digital y, además, una fila en
    'Cotizaciones' (misma cotización, para el seguimiento comercial general)
    con el número CD-XXXX como número de cotización y el total calculado
    como monto — así el vendedor no tiene que registrarla dos veces."""
    numero = _siguiente_numero_cotizacion_digital()
    numero_txt = f"CD-{numero:04d}"
    doc_ref = get_client().collection("cotizaciones_digital").document()
    doc_ref.set({
        "numero": numero, "prospecto_id": prospecto_id, "vendedor_id": vendedor_id,
        "nombre_producto": nombre_producto, "tipo_trabajo": tipo_trabajo,
        "detalle": detalle, "resultado": resultado, "notas": notas, "creado_por": creado_por,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    create_cotizacion(
        prospecto_id=prospecto_id, vendedor_id=vendedor_id,
        fecha_contacto=date.today(), fecha_cotizacion=date.today(),
        numero_cotizacion=numero_txt, monto=(resultado or {}).get("total") or 0.0,
        estado="Enviada", notas=f"Generado automáticamente desde Cotizador Digital ({nombre_producto}).",
    )
    return {"id": doc_ref.id, "numero": numero}


def update_cotizacion_digital(cotizacion_id, **kwargs):
    if kwargs:
        get_client().collection("cotizaciones_digital").document(cotizacion_id).update(kwargs)


def delete_cotizacion_digital(cotizacion_id):
    get_client().collection("cotizaciones_digital").document(cotizacion_id).delete()


# ---------------------------------------------------------------------------
# Mantenimiento de Tiendas: tablero de solicitudes estilo Trello, mismo
# concepto que el tablero de Diseño Gráfico ("disenos") — el jefe de tienda
# (o admin) reporta qué hay que arreglar, y el 'Jefe de Mantenimiento' la va
# moviendo por el tablero conforme avanza.
# ---------------------------------------------------------------------------
def list_mant_tiendas(tienda=None):
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("mant_tiendas").stream()]
    if tienda:
        rows = [r for r in rows if r.get("tienda") == tienda]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_mant_tienda(mant_id):
    snap = get_client().collection("mant_tiendas").document(mant_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def _siguiente_numero_mant_tienda():
    """Numeración corrida (no reinicia), empezando en 1 — el 'N° de
    solicitud' que se muestra en la tarjeta y en la orden de trabajo en PDF,
    igual que el número de envío de Logística."""
    rows = [_doc_to_dict(s) for s in get_client().collection("mant_tiendas").stream()]
    numeros = [r.get("numero_solicitud") for r in rows if isinstance(r.get("numero_solicitud"), int)]
    return (max(numeros, default=0)) + 1


def create_mant_tienda(creado_por_id, tienda, quien_solicita, descripcion, estado, fotos=None):
    ahora_txt = ahora_guatemala().isoformat(timespec="seconds")
    doc_ref = get_client().collection("mant_tiendas").document()
    doc_ref.set({
        "numero_solicitud": _siguiente_numero_mant_tienda(),
        "creado_por_id": creado_por_id, "tienda": tienda, "quien_solicita": quien_solicita,
        "descripcion": descripcion, "estado": estado, "detenido_emergencia": False,
        "fotos": fotos or [],
        "creado_en": ahora_txt,
        # Tipo de solicitud con el que se abrió el ticket ('Lista de tareas'
        # o 'Emergencia') — se guarda aparte de 'estado' porque 'estado' va
        # cambiando conforme la solicitud avanza por el tablero.
        "tipo_solicitud_inicial": estado,
        # Historial completo de etapas: se agrega una entrada cada vez que
        # la solicitud entra a una columna nueva (ver avanzar_mant_tienda) —
        # a diferencia de las 'fecha_*' de abajo (que solo guardan la
        # PRIMERA vez que se llega a cada una), esto registra TODAS las
        # veces, para poder calcular cuánto tiempo estuvo en cada columna
        # aunque la solicitud se haya movido hacia atrás y haya vuelto a
        # pasar por la misma columna más de una vez (ver utils.py,
        # mant_tienda_segmentos_etapa).
        "historial_etapas": [{"estado": estado, "entrada_en": ahora_txt}],
        # Hora exacta en la que la solicitud entró a cada etapa medida — se
        # llenan solo la primera vez que llega a esa etapa (ver
        # avanzar_mant_tienda). Se conservan por compatibilidad, pero los
        # KPIs de tiempo ahora se calculan a partir de 'historial_etapas'.
        "fecha_cotizacion": None, "fecha_en_proceso": None, "fecha_finalizado": None,
        # Cotización: PDFs subidos (máximo 3) y su autorización — solo el
        # admin puede autorizarla (ver autorizar_cotizacion_mant_tienda).
        "cotizacion_pdfs": [], "cotizacion_autorizada": False,
        "cotizacion_autorizada_por_id": None, "cotizacion_autorizada_en": None,
    })
    return doc_ref.id


def update_mant_tienda(mant_id, **kwargs):
    if kwargs:
        get_client().collection("mant_tiendas").document(mant_id).update(kwargs)


def subir_cotizacion_mant_tienda(mant_id, pdfs):
    """Guarda los archivos PDF de cotización de una solicitud (máximo 3,
    ver config.MANT_TIENDAS_COTIZACION_MAX_ARCHIVOS). Si ya había una
    cotización autorizada, subir archivos nuevos LE QUITA la autorización
    automáticamente — el admin tiene que volver a autorizar la cotización
    actualizada, para no dejar aprobado por error un PDF que ya cambió."""
    get_client().collection("mant_tiendas").document(mant_id).update({
        "cotizacion_pdfs": pdfs,
        "cotizacion_autorizada": False,
        "cotizacion_autorizada_por_id": None,
        "cotizacion_autorizada_en": None,
    })


def autorizar_cotizacion_mant_tienda(mant_id, autorizado_por_id):
    """Solo el admin puede llamar a esto (ver
    auth.puede_autorizar_cotizacion_mant_tiendas) — pone el semáforo de
    cotización en verde."""
    get_client().collection("mant_tiendas").document(mant_id).update({
        "cotizacion_autorizada": True,
        "cotizacion_autorizada_por_id": autorizado_por_id,
        "cotizacion_autorizada_en": ahora_guatemala().isoformat(timespec="seconds"),
    })


def desautorizar_cotizacion_mant_tienda(mant_id):
    """Le quita la autorización a una cotización ya autorizada (por ejemplo,
    si el admin se equivocó) — el semáforo vuelve a rojo."""
    get_client().collection("mant_tiendas").document(mant_id).update({
        "cotizacion_autorizada": False,
        "cotizacion_autorizada_por_id": None,
        "cotizacion_autorizada_en": None,
    })


# Campo de "hora de entrada" que se registra la primera vez que una
# solicitud llega a cada una de estas etapas — usado por avanzar_mant_tienda
# para medir cuánto tiempo se tarda cada proceso.
MANT_TIENDA_TS_POR_ESTADO = {
    "En cotización": "fecha_cotizacion",
    "En proceso": "fecha_en_proceso",
    "Finalizado": "fecha_finalizado",
}


def avanzar_mant_tienda(mant_id, nuevo_estado, extra=None):
    """Cambia el estado de una solicitud de Mantenimiento de Tiendas. Cada
    vez que el estado realmente cambia, se agrega una entrada nueva al
    historial completo ('historial_etapas') con la hora exacta de entrada a
    la columna nueva — esto queda registrado SIEMPRE, incluso si la
    solicitud se mueve hacia atrás y vuelve a pasar por la misma columna más
    de una vez, para poder calcular con exactitud cuánto tiempo estuvo en
    cada columna (ver utils.mant_tienda_segmentos_etapa, que usa este
    historial para los KPIs de tiempo de 20_Mant_Tiendas.py). Además, la
    primera vez que llega a una etapa medida (En cotización / En proceso /
    Finalizado) se sigue guardando también en las 'fecha_*' de siempre, por
    compatibilidad. 'extra' son otros campos a actualizar en la misma
    escritura (por ejemplo, si también se editaron los datos de la
    solicitud en el mismo formulario).

    Regla de negocio: no se puede entrar a 'En proceso' hasta que un admin
    autorice la cotización (ver auth.puede_autorizar_cotizacion_mant_tiendas
    y autorizar_cotizacion_mant_tienda) — lanza ValueError si se intenta sin
    autorización, para que la página lo muestre con st.error()."""
    actual = get_mant_tienda(mant_id) or {}
    if (
        nuevo_estado == "En proceso"
        and actual.get("estado") != "En proceso"
        and not actual.get("cotizacion_autorizada")
    ):
        raise ValueError(
            "No se puede mover esta solicitud a «En proceso» hasta que un administrador autorice la cotización."
        )
    cambios = dict(extra or {})
    cambios["estado"] = nuevo_estado
    if actual.get("estado") != nuevo_estado:
        ahora_txt = ahora_guatemala().isoformat(timespec="seconds")
        campo_ts = MANT_TIENDA_TS_POR_ESTADO.get(nuevo_estado)
        if campo_ts and not actual.get(campo_ts):
            cambios[campo_ts] = ahora_txt
        historial_actual = actual.get("historial_etapas") or []
        cambios["historial_etapas"] = historial_actual + [{"estado": nuevo_estado, "entrada_en": ahora_txt}]
    get_client().collection("mant_tiendas").document(mant_id).update(cambios)


def delete_mant_tienda(mant_id):
    get_client().collection("mant_tiendas").document(mant_id).delete()


def get_mant_tiendas_correos_aviso() -> list:
    """Lista de correos que reciben un aviso automático cuando se crea una
    solicitud NUEVA en el tablero de Mantenimiento de Tiendas (ver
    20_Mant_Tiendas.py) — a propósito no se manda nada cuando una solicitud
    cambia de columna/etapa (pedido explícito de Steven). Vacía si todavía
    no se ha guardado ninguno."""
    snap = get_client().collection("mant_tiendas_config").document("notificaciones").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_mant_tiendas_correos_aviso(correos: list):
    get_client().collection("mant_tiendas_config").document("notificaciones").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Drive — "Datos generales" (ventas totales, por línea, flujo, ticket
# promedio) y "Krispy 2". Trae a la plataforma los números que Steven llevaba
# en un Google Sheet aparte ("DASHBOARD VD"); a partir de aquí se editan
# directamente en la pestaña Drive — no hay sincronización con el Google
# Sheet original. Los datos históricos se cargan UNA SOLA VEZ, la primera vez
# que arranca la app con esta pestaña (ver _seed_dg_datos / _seed_krispy_datos,
# llamadas desde init_db, mismo patrón que _seed_logistica_vendedores).
# ---------------------------------------------------------------------------
def _slug(texto: str) -> str:
    """Convierte un texto (nombre de tienda/línea) en algo seguro para usar
    como parte de un ID de documento de Firestore."""
    return str(texto).strip().upper().replace(" ", "_")


def _dg_doc_id(categoria, entidad, anio, meta) -> str:
    """ID de documento FIJO (no autogenerado) para un registro de 'Datos
    generales' — así, guardar dos veces la misma combinación de categoría +
    entidad + año + tipo (real/meta) siempre cae en el MISMO documento
    (se sobreescribe) en vez de crear uno nuevo. Esto es lo que evita que se
    guarden registros duplicados si, por ejemplo, la app arranca dos veces
    al mismo tiempo (como pasó con la carga inicial de datos)."""
    return f"{categoria}-{_slug(entidad)}-{int(anio)}-{'meta' if meta else 'real'}"


def _krispy_doc_id(tienda, anio, mes) -> str:
    """Mismo concepto que _dg_doc_id, para un registro de 'Krispy 2'."""
    return f"{_slug(tienda)}-{int(anio)}-{_slug(mes)}"


def get_dg_datos(categoria, entidad=None):
    """Retorna la lista de registros {categoria, entidad, anio, meta, valores,
    ...} de 'Datos generales' para la categoría indicada (y, si se da, solo
    esa entidad) — todos los años disponibles, ordenados por año y con la
    fila de meta (si existe) después de la real de ese mismo año."""
    client = get_client()
    query = client.collection("dg_datos").where("categoria", "==", categoria)
    if entidad:
        query = query.where("entidad", "==", entidad)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: (int(r.get("anio") or 0), bool(r.get("meta"))))
    return rows


def upsert_dg_dato(categoria, entidad, anio, meta, valores):
    """valores: dict {MES: monto/cantidad}, con los meses en mayúsculas sin
    acentos (ver config.DG_MESES). Guarda siempre en el mismo documento para
    esa combinación exacta de categoría + entidad + año + tipo (meta o real)
    — ver _dg_doc_id — así que reemplaza el valor anterior si ya existía, o
    lo crea si no, sin poder duplicarse."""
    client = get_client()
    data = {
        "categoria": categoria, "entidad": entidad, "anio": int(anio), "meta": bool(meta),
        "valores": valores, "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    client.collection("dg_datos").document(_dg_doc_id(categoria, entidad, anio, meta)).set(data)


def get_krispy_datos(anio=None, tienda=None):
    """Retorna la lista de registros {tienda, anio, mes, valores, ...} de
    'Krispy 2' (opcionalmente filtrados por año y/o tienda), ordenados por
    tienda y luego por mes en orden de calendario."""
    from config import DG_MESES
    client = get_client()
    query = client.collection("krispy2_datos")
    if anio is not None:
        query = query.where("anio", "==", int(anio))
    if tienda:
        query = query.where("tienda", "==", tienda)
    rows = [_doc_to_dict(s) for s in query.stream()]
    orden_mes = {m: i for i, m in enumerate(DG_MESES)}
    rows.sort(key=lambda r: (r.get("tienda", ""), orden_mes.get(r.get("mes"), 99)))
    return rows


def upsert_krispy_dato(tienda, anio, mes, valores):
    """valores: dict con las claves unidades_bites/unidades_mini/dinero_bites/
    dinero_mini/utilidad_bites/utilidad_mini. Guarda siempre en el mismo
    documento para esa tienda + año + mes (ver _krispy_doc_id), así que
    reemplaza el valor anterior si ya existía, o lo crea si no, sin poder
    duplicarse."""
    client = get_client()
    data = {
        "tienda": tienda, "anio": int(anio), "mes": mes, "valores": valores,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    client.collection("krispy2_datos").document(_krispy_doc_id(tienda, anio, mes)).set(data)


def eliminar_duplicados_dg_datos() -> int:
    """Por un problema ya corregido en la carga inicial (dos arranques de la
    app al mismo tiempo guardando cada uno su propia copia), es posible que
    algunos registros de 'Datos generales' hayan quedado duplicados —misma
    categoría + entidad + año + tipo repetida en más de un documento. Esta
    función los revisa todos y, donde encuentra más de uno para la misma
    combinación, se queda con el más reciente y borra el resto. Se puede
    llamar las veces que sea: si ya no hay duplicados, no borra nada.
    Retorna cuántos documentos se borraron."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("dg_datos").stream()]
    grupos = {}
    for r in rows:
        clave = (r.get("categoria"), r.get("entidad"), int(r.get("anio") or 0), bool(r.get("meta")))
        grupos.setdefault(clave, []).append(r)
    borrados = 0
    for docs in grupos.values():
        if len(docs) <= 1:
            continue
        docs_ordenados = sorted(docs, key=lambda d: d.get("actualizado_en") or "", reverse=True)
        for d in docs_ordenados[1:]:
            client.collection("dg_datos").document(d["id"]).delete()
            borrados += 1
    return borrados


def eliminar_duplicados_krispy_datos() -> int:
    """Mismo concepto que eliminar_duplicados_dg_datos, para 'Krispy 2'
    (agrupando por tienda + año + mes)."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("krispy2_datos").stream()]
    grupos = {}
    for r in rows:
        clave = (r.get("tienda"), int(r.get("anio") or 0), r.get("mes"))
        grupos.setdefault(clave, []).append(r)
    borrados = 0
    for docs in grupos.values():
        if len(docs) <= 1:
            continue
        docs_ordenados = sorted(docs, key=lambda d: d.get("actualizado_en") or "", reverse=True)
        for d in docs_ordenados[1:]:
            client.collection("krispy2_datos").document(d["id"]).delete()
            borrados += 1
    return borrados


def _seed_dg_datos(client):
    """Carga los datos históricos de 'Datos generales' (dg_seed.json,
    extraídos del Google Sheet original 'DASHBOARD VD') la primera vez que
    arranca la app con esta pestaña — no repite nada si ya hay datos
    guardados (incluyendo si ya se editó algo desde la pestaña Drive). Usa
    _dg_doc_id (ID fijo) para que, aunque esta función se llegue a ejecutar
    dos veces al mismo tiempo (dos arranques simultáneos de la app), nunca
    pueda crear registros duplicados — cada combinación cae siempre en el
    mismo documento."""
    existentes = list(client.collection("dg_datos").limit(1).stream())
    if existentes:
        return
    ruta = os.path.join(BASE_DIR, "dg_seed.json")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        seed = json.load(f)
    for categoria, entidades in seed.items():
        for entidad, registros in entidades.items():
            for r in registros:
                anio, meta = int(r["anio"]), bool(r["meta"])
                client.collection("dg_datos").document(_dg_doc_id(categoria, entidad, anio, meta)).set({
                    "categoria": categoria, "entidad": entidad, "anio": anio, "meta": meta,
                    "valores": r["valores"], "actualizado_en": datetime.now().isoformat(timespec="seconds"),
                })


def _seed_krispy_datos(client):
    """Carga los datos históricos de 'Krispy 2' (krispy_seed.json) la
    primera vez que arranca la app con esta pestaña. El Google Sheet original
    no tiene columna de año — se asumió config.KRISPY_ANIO_ASUMIDO (2026); si
    no es correcto, se puede corregir mes por mes desde la pestaña Drive. Usa
    _krispy_doc_id (ID fijo) por la misma razón que _seed_dg_datos: para que
    no pueda crear registros duplicados aunque se ejecute dos veces a la vez."""
    from config import KRISPY_ANIO_ASUMIDO
    existentes = list(client.collection("krispy2_datos").limit(1).stream())
    if existentes:
        return
    ruta = os.path.join(BASE_DIR, "krispy_seed.json")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        seed = json.load(f)
    for tienda, meses in seed.items():
        for mes, valores in meses.items():
            client.collection("krispy2_datos").document(_krispy_doc_id(tienda, KRISPY_ANIO_ASUMIDO, mes)).set({
                "tienda": tienda, "anio": KRISPY_ANIO_ASUMIDO, "mes": mes, "valores": valores,
                "actualizado_en": datetime.now().isoformat(timespec="seconds"),
            })


# ---------------------------------------------------------------------------
# Historial (pestaña "Historial" dentro de "Ventas por mes"): serie
# histórica año por año, mes por mes, de la Venta total y la Utilidad total
# de la empresa (viene del Excel aparte que llevaba Steven). Mismo concepto
# que 'Datos generales' de Drive (fila real + fila opcional de meta, por
# año), pero en su propia colección — no se mezcla con Drive ni con el
# desglose por vendedor/planta de 'Ventas por mes'/'Utilidades'.
# ---------------------------------------------------------------------------
def _historial_doc_id(categoria, anio, meta) -> str:
    """Mismo concepto que _dg_doc_id: ID fijo (no autogenerado) para que
    guardar dos veces la misma categoría + año + tipo (real/meta) siempre
    caiga en el mismo documento, sin poder duplicarse."""
    return f"{categoria}-{int(anio)}-{'meta' if meta else 'real'}"


def get_historial_datos(categoria):
    """Retorna la lista de registros {categoria, anio, meta, valores, ...}
    del Historial para la categoría indicada ('venta' o 'utilidad'), todos
    los años disponibles, ordenados por año y con la fila de meta (si
    existe) después de la real de ese mismo año."""
    client = get_client()
    query = client.collection("historial_vpm").where("categoria", "==", categoria)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: (int(r.get("anio") or 0), bool(r.get("meta"))))
    return rows


def upsert_historial_dato(categoria, anio, meta, valores):
    """valores: dict {MES: monto}, con los meses en mayúsculas sin acentos
    (ver config.DG_MESES). Guarda siempre en el mismo documento para esa
    combinación exacta de categoría + año + tipo (meta o real) — ver
    _historial_doc_id — así que reemplaza el valor anterior si ya existía,
    o lo crea si no."""
    client = get_client()
    data = {
        "categoria": categoria, "anio": int(anio), "meta": bool(meta),
        "valores": valores, "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    }
    client.collection("historial_vpm").document(_historial_doc_id(categoria, anio, meta)).set(data)


def eliminar_duplicados_historial_vpm() -> int:
    """Mismo concepto que eliminar_duplicados_dg_datos, para el Historial
    (agrupando por categoría + año + tipo)."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("historial_vpm").stream()]
    grupos = {}
    for r in rows:
        clave = (r.get("categoria"), int(r.get("anio") or 0), bool(r.get("meta")))
        grupos.setdefault(clave, []).append(r)
    borrados = 0
    for docs in grupos.values():
        if len(docs) <= 1:
            continue
        docs_ordenados = sorted(docs, key=lambda d: d.get("actualizado_en") or "", reverse=True)
        for d in docs_ordenados[1:]:
            client.collection("historial_vpm").document(d["id"]).delete()
            borrados += 1
    return borrados


def _seed_historial_vpm(client):
    """Carga los datos históricos del Historial (historial_vpm_seed.json,
    extraídos del Excel 'VENTAS PARA PLATAFORMA' que mandó Steven) la
    primera vez que arranca la app con esta pestaña — no repite nada si ya
    hay datos guardados (incluyendo si ya se editó algo desde la pestaña).
    Usa _historial_doc_id (ID fijo) para que, aunque esta función se llegue
    a ejecutar dos veces al mismo tiempo, nunca pueda crear duplicados."""
    existentes = list(client.collection("historial_vpm").limit(1).stream())
    if existentes:
        return
    ruta = os.path.join(BASE_DIR, "historial_vpm_seed.json")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        seed = json.load(f)
    for categoria, registros in seed.items():
        for r in registros:
            anio, meta = int(r["anio"]), bool(r["meta"])
            client.collection("historial_vpm").document(_historial_doc_id(categoria, anio, meta)).set({
                "categoria": categoria, "anio": anio, "meta": meta,
                "valores": r["valores"], "actualizado_en": datetime.now().isoformat(timespec="seconds"),
            })


def delete_historial_dato(categoria, anio, meta):
    """Borra una fila puntual del Historial (esa categoría + año + tipo
    real/meta), si existe. Usado desde el botón 'Eliminar' de la pestaña."""
    get_client().collection("historial_vpm").document(_historial_doc_id(categoria, anio, meta)).delete()


def limpiar_historial_metas_fuera_de_2026() -> int:
    """Corrección puntual (pedido de Steven): la fila de meta (objetivo) del
    Historial solo aplica al año en curso, 2026 — los años anteriores
    (2023, 2024, 2025) no deben tener fila de meta propia. Borra cualquier
    fila de meta que haya quedado guardada para un año distinto de 2026, en
    Venta y en Utilidad. Se puede llamar las veces que sea: si ya no queda
    ninguna, no borra nada."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("historial_vpm").stream()]
    borrados = 0
    for r in rows:
        if r.get("meta") and int(r.get("anio") or 0) != 2026:
            client.collection("historial_vpm").document(r["id"]).delete()
            borrados += 1
    return borrados


# ---------------------------------------------------------------------------
# Phara (cliente): cronograma de entregas + tablero de producción estilo
# Trello. Cada "pedido" es a la vez una fila del cronograma (tiene fecha de
# entrega) y una tarjeta del tablero (tiene una etapa — ver config.ESTADOS_PHARA).
# ---------------------------------------------------------------------------
def list_phara_pedidos():
    """Retorna todos los pedidos de Phara, más nuevos primero."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("phara_pedidos").stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_phara_pedido(pedido_id):
    snap = get_client().collection("phara_pedidos").document(pedido_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_phara_pedido(producto, cantidad, fecha_entrega, notas=None, creado_por_id=None):
    """Todo pedido nuevo entra siempre por la primera columna del tablero
    ('Sherpa') — ver config.ESTADOS_PHARA."""
    from config import ESTADOS_PHARA
    doc_ref = get_client().collection("phara_pedidos").document()
    doc_ref.set({
        "producto": producto, "cantidad": cantidad,
        "fecha_entrega": str(fecha_entrega) if fecha_entrega else None,
        "estado": ESTADOS_PHARA[0], "notas": notas or None,
        "creado_por_id": creado_por_id, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def update_phara_pedido(pedido_id, **kwargs):
    if kwargs:
        get_client().collection("phara_pedidos").document(pedido_id).update(kwargs)


def delete_phara_pedido(pedido_id):
    get_client().collection("phara_pedidos").document(pedido_id).delete()


def get_phara_correos_aviso() -> list:
    """Lista de correos que reciben un aviso automático cuando se agrega un
    pedido nuevo o una tarjeta cambia de columna en el tablero de Phara (ver
    22_Phara.py). Vacía si todavía no se ha guardado ninguno."""
    snap = get_client().collection("phara_config").document("notificaciones").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_phara_correos_aviso(correos: list):
    get_client().collection("phara_config").document("notificaciones").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Documentos: biblioteca de PDFs (catálogos, precios, manuales, etc.)
# organizada por categoría — ver config.DOCUMENTOS_CATEGORIAS. Solo el
# admin sube/elimina; vendedor, vista, mercadeo y admin pueden consultar y
# descargar (ver app_pages/23_Documentos.py y app.py). El archivo se guarda
# en Firebase Storage si está disponible (ver storage_disponible arriba);
# si no, cae al guardado anterior en base64 dentro del documento.
# ---------------------------------------------------------------------------
def list_documentos(categoria=None):
    """Todos los documentos, más reciente primero; si se pasa categoria,
    solo los de esa categoría."""
    rows = [_doc_to_dict(s) for s in get_client().collection("documentos").stream()]
    if categoria:
        rows = [r for r in rows if r.get("categoria") == categoria]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_documento(documento_id):
    snap = get_client().collection("documentos").document(documento_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_documento(titulo, categoria, descripcion, archivo_info, creado_por_id=None):
    get_client().collection("documentos").document().set({
        "titulo": titulo, "categoria": categoria, "descripcion": descripcion or None,
        **archivo_info,
        "creado_por_id": creado_por_id, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })


def delete_documento(documento_id):
    doc = get_documento(documento_id)
    get_client().collection("documentos").document(documento_id).delete()
    if doc and doc.get("storage_path"):
        eliminar_archivos_storage([doc])


# ---------------------------------------------------------------------------
# Horarios y Limpieza (dentro de Minutas de Tienda): UN documento de
# "Horario" y UN documento de "Limpieza" por tienda (PDF o Excel) — subir uno
# nuevo reemplaza al anterior, no se acumulan versiones. Por eso el id del
# documento es determinístico (tienda+tipo), en vez de uno aleatorio como en
# "documentos" (que sí permite varios por categoría).
# ---------------------------------------------------------------------------
def _tienda_doc_id(tienda, tipo):
    crudo = f"{tienda}_{tipo}".strip().lower().replace(" ", "_")
    return "".join(c for c in crudo if c.isalnum() or c == "_") or "doc"


def get_tienda_documento(tienda, tipo):
    snap = get_client().collection("tienda_documentos").document(_tienda_doc_id(tienda, tipo)).get()
    return _doc_to_dict(snap) if snap.exists else None


def set_tienda_documento(tienda, tipo, archivo_info, actualizado_por_id=None, actualizado_por_nombre=None):
    """Guarda (o reemplaza) el documento de 'tipo' ('Horario'/'Limpieza') de
    una tienda. Si ya había uno subido a Firebase Storage, lo borra de
    Storage al reemplazarlo (no se acumulan archivos huérfanos)."""
    anterior = get_tienda_documento(tienda, tipo)
    get_client().collection("tienda_documentos").document(_tienda_doc_id(tienda, tipo)).set({
        "tienda": tienda, "tipo": tipo,
        **archivo_info,
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
        "actualizado_por_id": actualizado_por_id, "actualizado_por_nombre": actualizado_por_nombre,
    })
    if anterior and anterior.get("storage_path"):
        eliminar_archivos_storage([anterior])


def delete_tienda_documento(tienda, tipo):
    doc = get_tienda_documento(tienda, tipo)
    get_client().collection("tienda_documentos").document(_tienda_doc_id(tienda, tipo)).delete()
    if doc and doc.get("storage_path"):
        eliminar_archivos_storage([doc])


# ---------------------------------------------------------------------------
# Colorado (planta): órdenes de producción — mismo concepto que Phara
# (cronograma de entregas + tablero de producción estilo Trello + avisos por
# correo), pero de uso interno: ver config.ESTADOS_COLORADO y
# auth.puede_editar_colorado.
# ---------------------------------------------------------------------------
def list_colorado_pedidos():
    """Retorna todas las órdenes de Colorado, más nuevas primero."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("colorado_pedidos").stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_colorado_pedido(pedido_id):
    snap = get_client().collection("colorado_pedidos").document(pedido_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def _siguiente_numero_colorado():
    """Numeración corrida (no reinicia), empezando en 1 — el 'N° de orden'
    que se muestra en la orden de producción en PDF, igual que el número de
    envío de Logística."""
    rows = [_doc_to_dict(s) for s in get_client().collection("colorado_pedidos").stream()]
    numeros = [r.get("numero_orden") for r in rows if isinstance(r.get("numero_orden"), int)]
    return (max(numeros, default=0)) + 1


def create_colorado_pedido(datos: dict, creado_por_id=None):
    """Toda orden nueva entra siempre por la primera columna del tablero
    ('Nuevo') — ver config.ESTADOS_COLORADO. 'datos' trae los campos de la
    orden de producción (cliente, pieza, dimensiones, material, color,
    acabados, precio, cantidad, notas, NIT, dirección, fecha de entrega,
    archivos adjuntos — ver app_pages/24_Colorado.py)."""
    from config import ESTADOS_COLORADO
    doc_ref = get_client().collection("colorado_pedidos").document()
    doc_ref.set({
        **datos,
        "estado": ESTADOS_COLORADO[0], "numero_orden": _siguiente_numero_colorado(),
        "creado_por_id": creado_por_id, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def update_colorado_pedido(pedido_id, **kwargs):
    if kwargs:
        get_client().collection("colorado_pedidos").document(pedido_id).update(kwargs)


def delete_colorado_pedido(pedido_id):
    doc = get_colorado_pedido(pedido_id)
    get_client().collection("colorado_pedidos").document(pedido_id).delete()
    if doc and doc.get("archivos"):
        eliminar_archivos_storage(doc["archivos"])


def get_colorado_correos_aviso() -> list:
    """Lista de correos que reciben un aviso automático cuando se agrega una
    orden nueva o una tarjeta cambia de columna en el tablero de Colorado
    (ver 24_Colorado.py). Vacía si todavía no se ha guardado ninguno."""
    snap = get_client().collection("colorado_config").document("notificaciones").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_colorado_correos_aviso(correos: list):
    get_client().collection("colorado_config").document("notificaciones").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Galaxy: idéntico a Colorado (cronograma de entregas + tablero de
# producción estilo Trello + avisos por correo), pero como línea de
# producción / colección de datos totalmente independiente — ver
# config.ESTADOS_GALAXY y auth.puede_editar_galaxy.
# ---------------------------------------------------------------------------
def list_galaxy_pedidos():
    """Retorna todas las órdenes de Galaxy, más nuevas primero."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("galaxy_pedidos").stream()]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def get_galaxy_pedido(pedido_id):
    snap = get_client().collection("galaxy_pedidos").document(pedido_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def _siguiente_numero_galaxy():
    """Numeración corrida (no reinicia), empezando en 1 — el 'N° de orden'
    que se muestra en la orden de producción en PDF, igual que el número de
    envío de Logística."""
    rows = [_doc_to_dict(s) for s in get_client().collection("galaxy_pedidos").stream()]
    numeros = [r.get("numero_orden") for r in rows if isinstance(r.get("numero_orden"), int)]
    return (max(numeros, default=0)) + 1


def create_galaxy_pedido(datos: dict, creado_por_id=None):
    """Toda orden nueva entra siempre por la primera columna del tablero
    ('Nuevo') — ver config.ESTADOS_GALAXY. 'datos' trae los campos de la
    orden de producción (cliente, pieza, dimensiones, material, color,
    acabados, precio, cantidad, notas, NIT, dirección, fecha de entrega,
    archivos adjuntos — ver app_pages/25_Galaxy.py)."""
    from config import ESTADOS_GALAXY
    doc_ref = get_client().collection("galaxy_pedidos").document()
    doc_ref.set({
        **datos,
        "estado": ESTADOS_GALAXY[0], "numero_orden": _siguiente_numero_galaxy(),
        "creado_por_id": creado_por_id, "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def update_galaxy_pedido(pedido_id, **kwargs):
    if kwargs:
        get_client().collection("galaxy_pedidos").document(pedido_id).update(kwargs)


def delete_galaxy_pedido(pedido_id):
    doc = get_galaxy_pedido(pedido_id)
    get_client().collection("galaxy_pedidos").document(pedido_id).delete()
    if doc and doc.get("archivos"):
        eliminar_archivos_storage(doc["archivos"])


def get_galaxy_correos_aviso() -> list:
    """Lista de correos que reciben un aviso automático cuando se agrega una
    orden nueva o una tarjeta cambia de columna en el tablero de Galaxy (ver
    25_Galaxy.py). Vacía si todavía no se ha guardado ninguno."""
    snap = get_client().collection("galaxy_config").document("notificaciones").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_galaxy_correos_aviso(correos: list):
    get_client().collection("galaxy_config").document("notificaciones").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Avisos por correo (Gmail) — usado por la pestaña Phara para avisar cuando
# hay un pedido nuevo o un cambio de columna. Mismo patrón que Firebase
# Storage: si todavía no están las credenciales configuradas, estas
# funciones simplemente no hacen nada (no rompen el resto de la página).
# ---------------------------------------------------------------------------
def _smtp_config():
    """Lee las credenciales de Gmail desde st.secrets['gmail_notificaciones']
    (tabla con 'usuario' y 'app_password' — ver instrucciones de
    configuración). Retorna None si todavía no están configuradas."""
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
        msg["From"] = formataddr((EMPRESA_NOMBRE, conf["usuario"]))
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
    adjunto (por ejemplo el PDF de una Minuta de Tienda — ver
    utils.minuta_tienda_pdf_bytes / 28_Minutas_Tiendas.py). Si
    'adjunto_bytes' es None manda un correo de texto plano normal, sin
    adjunto. Nunca lanza excepción — mismo comportamiento a prueba de
    fallos que enviar_correo_aviso: si algo falla, retorna False y el
    detalle queda solo en el log del servidor."""
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
        msg["From"] = formataddr((EMPRESA_NOMBRE, conf["usuario"]))
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


# ---------------------------------------------------------------------------
# NPS (Net Promoter Score): encuesta pública de servicio al cliente, con
# check-in por QR — una por tienda (ver config.NPS_TIENDA_SLUG). La encuesta
# la llena el cliente desde su celular, sin iniciar sesión (ver
# public_nps.py); la parametrización de las preguntas y el dashboard de
# KPIs se consultan/editan desde la pestaña NPS (app_pages/26_NPS.py).
# ---------------------------------------------------------------------------
_NPS_CONFIG_DOC_ID = "preguntas"


def get_nps_preguntas():
    """Retorna la lista de preguntas configuradas — [{"id","tipo","texto",
    "opciones"?}, ...]. Si todavía no se ha guardado nada (parametrización
    nunca tocada), retorna el valor de fábrica (config.NPS_PREGUNTAS_INICIAL)
    sin necesidad de sembrarlo antes en la base de datos."""
    from config import NPS_PREGUNTAS_INICIAL
    client = get_client()
    snap = client.collection("nps_config").document(_NPS_CONFIG_DOC_ID).get()
    data = _doc_to_dict(snap) if snap.exists else None
    if data and data.get("preguntas"):
        return data["preguntas"]
    return NPS_PREGUNTAS_INICIAL


def set_nps_preguntas(preguntas):
    """Guarda la lista completa de preguntas configuradas (reemplaza todo lo
    que hubiera guardado antes) — preguntas: lista de dicts con la misma
    forma que config.NPS_PREGUNTAS_INICIAL."""
    client = get_client()
    client.collection("nps_config").document(_NPS_CONFIG_DOC_ID).set({
        "preguntas": preguntas, "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def create_nps_respuesta(tienda, respuestas, nombre_contacto=None, telefono_contacto=None):
    """Guarda una respuesta de la encuesta pública. 'respuestas' es un dict
    {pregunta_id: valor} — para una pregunta 'carita', valor es uno de
    'malo'/'regular'/'excelente' (ver config.NPS_CARITAS); para 'opcion', el
    texto de la opción elegida; para 'texto', el comentario libre (puede
    venir vacío/None, esa pregunta es opcional). 'nombre_contacto' y
    'telefono_contacto' son del formulario opcional al final de la encuesta
    ("¿quieres que te contactemos?") — no son parte de las preguntas, van
    aparte porque no siempre se llenan."""
    client = get_client()
    client.collection("nps_respuestas").document().set({
        "tienda": tienda, "respuestas": respuestas,
        "nombre_contacto": (nombre_contacto or "").strip() or None,
        "telefono_contacto": (telefono_contacto or "").strip() or None,
        # Hora de Guatemala (no la del servidor, que corre en UTC) — así la
        # columna "Fecha" de los comentarios en la pestaña NPS sale correcta.
        "creado_en": ahora_guatemala().isoformat(timespec="seconds"),
    })


def list_nps_respuestas(tienda=None, desde=None, hasta=None):
    """Todas las respuestas de la encuesta NPS, más nuevas primero,
    opcionalmente filtradas por tienda y/o por rango de fechas (desde/hasta
    son date, ambos límites inclusive, comparados contra la fecha de
    'creado_en')."""
    client = get_client()
    rows = [_doc_to_dict(s) for s in client.collection("nps_respuestas").stream()]
    if tienda:
        rows = [r for r in rows if r.get("tienda") == tienda]
    if desde:
        rows = [r for r in rows if (r.get("creado_en") or "")[:10] >= str(desde)]
    if hasta:
        rows = [r for r in rows if (r.get("creado_en") or "")[:10] <= str(hasta)]
    rows.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return rows


def delete_nps_respuesta(respuesta_id):
    """Elimina una sola respuesta de la encuesta NPS (por su id)."""
    client = get_client()
    client.collection("nps_respuestas").document(respuesta_id).delete()


def delete_nps_respuestas(tienda=None, desde=None, hasta=None):
    """Elimina en bloque las respuestas de NPS que cumplan el filtro dado
    (mismo filtro que list_nps_respuestas: tienda y/o rango de fechas). Sin
    ningún filtro, elimina TODAS las respuestas. Devuelve cuántas se
    eliminaron."""
    rows = list_nps_respuestas(tienda=tienda, desde=desde, hasta=hasta)
    client = get_client()
    for r in rows:
        client.collection("nps_respuestas").document(r["id"]).delete()
    return len(rows)


# ---------------------------------------------------------------------------
# Minutas de Tienda: el jefe (o sub jefe) de tienda deja constancia de una
# reunión — un checklist de los temas tratados y una lista de pendientes que
# quedaron abiertos. El jefe de línea (o admin) le da seguimiento a cada
# pendiente por separado (cambia su estado y puede ir dejando comentarios de
# seguimiento) hasta que queda resuelto. Cada pendiente vive como un elemento
# dentro del arreglo "pendientes" de su minuta (igual que "fotos" en Mant.
# Tiendas) — no es una colección aparte, así que se actualiza con un
# lee-modifica-escribe completo del arreglo (ver update_pendiente_minuta).
# ---------------------------------------------------------------------------
def get_temas_predeterminados_minuta() -> list:
    """Lista de temas predeterminados que aparecen como checklist al crear
    una Minuta de Tienda — el jefe de tienda solo los marca si se tocaron,
    en vez de escribirlos de cero cada vez. Vacía si todavía no se ha
    configurado ninguno (ver set_temas_predeterminados_minuta — se edita
    desde la pestaña ⚙️ dentro de Minutas de Tienda, solo admin/jefe_linea)."""
    snap = get_client().collection("minutas_tiendas_config").document("temas").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("temas") or []


def set_temas_predeterminados_minuta(temas: list):
    get_client().collection("minutas_tiendas_config").document("temas").set({
        "temas": [t.strip() for t in (temas or []) if t and t.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def get_minutas_tiendas_correos_aviso() -> list:
    """Lista de correos que reciben automáticamente el PDF de la minuta
    (checklist + pendientes + metas vs. ventas) cada vez que se crea una
    minuta nueva (ver create_minuta_tienda / 28_Minutas_Tiendas.py). Vacía
    si todavía no se ha guardado ninguno."""
    snap = get_client().collection("minutas_tiendas_config").document("notificaciones").get()
    data = _doc_to_dict(snap) if snap.exists else None
    return (data or {}).get("correos") or []


def set_minutas_tiendas_correos_aviso(correos: list):
    get_client().collection("minutas_tiendas_config").document("notificaciones").set({
        "correos": [c.strip() for c in (correos or []) if c and c.strip()],
        "actualizado_en": datetime.now().isoformat(timespec="seconds"),
    })


def _siguiente_numero_minuta():
    """Numeración corrida (no reinicia por día) — MIN-0001, MIN-0002, ..."""
    rows = [_doc_to_dict(s) for s in get_client().collection("minutas_tiendas").stream()]
    numeros = [r.get("numero") for r in rows if isinstance(r.get("numero"), int)]
    return (max(numeros, default=0)) + 1


def list_minutas_tiendas(tienda=None):
    """Todas las minutas, más nueva primero (por fecha de la reunión y,
    dentro del mismo día, por hora de creación)."""
    client = get_client()
    query = client.collection("minutas_tiendas")
    if tienda:
        query = query.where("tienda", "==", tienda)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: (r.get("fecha_reunion") or "", r.get("creado_en") or ""), reverse=True)
    return rows


def get_minuta_tienda(minuta_id):
    snap = get_client().collection("minutas_tiendas").document(minuta_id).get()
    return _doc_to_dict(snap) if snap.exists else None


def create_minuta_tienda(creado_por_id, creado_por_nombre, tienda, fecha_reunion, checklist, pendientes, notas_generales=None):
    """'checklist' es una lista de {"tema": str, "tratado": bool, "extra":
    bool} — "extra" marca los temas que el jefe agregó a mano porque no
    estaban en la lista de temas predeterminados (ver
    get_temas_predeterminados_minuta). 'pendientes' es una lista de
    {"descripcion": str, "responsable": str, "fecha_limite": str|None} — al
    crearse, a cada pendiente se le agrega aquí mismo estado="Pendiente" y
    seguimiento=[] (ver config.ESTADOS_PENDIENTE_MINUTA)."""
    numero = _siguiente_numero_minuta()
    pendientes_completos = [
        {
            "descripcion": p["descripcion"], "responsable": p.get("responsable") or "",
            "fecha_limite": p.get("fecha_limite"), "estado": "Pendiente", "seguimiento": [],
        }
        for p in pendientes
    ]
    doc_ref = get_client().collection("minutas_tiendas").document()
    doc_ref.set({
        "numero": numero, "tienda": tienda, "fecha_reunion": str(fecha_reunion),
        "creado_por_id": creado_por_id, "creado_por_nombre": creado_por_nombre,
        "checklist": checklist, "pendientes": pendientes_completos,
        "notas_generales": (notas_generales or "").strip() or None,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    return doc_ref.id


def update_minuta_tienda(minuta_id, **kwargs):
    if kwargs:
        get_client().collection("minutas_tiendas").document(minuta_id).update(kwargs)


def delete_minuta_tienda(minuta_id):
    get_client().collection("minutas_tiendas").document(minuta_id).delete()


def update_pendiente_minuta(minuta_id, indice_pendiente, estado=None, comentario=None, autor_nombre=None):
    """Actualiza UN pendiente dentro del arreglo "pendientes" de una minuta
    — cambia su estado y/o agrega una entrada al historial de seguimiento
    (comentario + quién lo dejó + cuándo). No hace nada si el índice ya no
    existe (por ejemplo si alguien más lo eliminó mientras tanto)."""
    minuta = get_minuta_tienda(minuta_id)
    if not minuta:
        return
    pendientes = minuta.get("pendientes") or []
    if not (0 <= indice_pendiente < len(pendientes)):
        return
    if estado:
        pendientes[indice_pendiente]["estado"] = estado
    if comentario and comentario.strip():
        pendientes[indice_pendiente].setdefault("seguimiento", []).append({
            "comentario": comentario.strip(), "autor_nombre": autor_nombre or "—",
            "creado_en": datetime.now().isoformat(timespec="seconds"),
        })
    get_client().collection("minutas_tiendas").document(minuta_id).update({"pendientes": pendientes})


# ---------------------------------------------------------------------------
# Metas de Ventas por Tienda: el jefe (o sub jefe) de tienda le pone una
# meta mensual en quetzales a cada asesor de ventas de su sucursal (los
# mismos nombres de la colección "personal_tiendas", con rol
# "asesor_ventas" — ver PERSONAL_TIENDA_INICIAL en config.py) y va
# actualizando su venta del mes conforme avanza. La clave de cada registro
# es tienda + asesor + mes ("YYYY-MM") — dentro del MISMO mes se puede
# corregir/actualizar la venta las veces que haga falta (upsert), pero al
# entrar a un mes nuevo se crea un documento aparte, así queda el
# historial completo mes a mes sin perder los anteriores.
# ---------------------------------------------------------------------------
def mes_actual() -> str:
    """Mes actual en formato 'YYYY-MM', hora de Guatemala."""
    return str(hoy_guatemala())[:7]


def list_metas_tienda(tienda=None, mes=None):
    """Todos los registros de metas, más reciente primero. Filtra por
    tienda y/o por mes ('YYYY-MM') si se dan."""
    client = get_client()
    query = client.collection("metas_tienda")
    if tienda:
        query = query.where("tienda", "==", tienda)
    if mes:
        query = query.where("mes", "==", mes)
    rows = [_doc_to_dict(s) for s in query.stream()]
    rows.sort(key=lambda r: (r.get("mes") or "", r.get("asesor_nombre") or ""), reverse=True)
    return rows


def get_meta_tienda(tienda, asesor_nombre, mes):
    """El registro puntual de un asesor en un mes en particular, o None si
    todavía no se ha guardado nada para ese mes (para saber si hay que
    crear uno nuevo o actualizar el existente — ver upsert_meta_tienda)."""
    client = get_client()
    rows = [
        _doc_to_dict(s) for s in client.collection("metas_tienda")
        .where("tienda", "==", tienda).where("asesor_nombre", "==", asesor_nombre).where("mes", "==", mes)
        .limit(1).stream()
    ]
    return rows[0] if rows else None


def upsert_meta_tienda(tienda, asesor_nombre, mes, meta=None, venta_actual=None, actualizado_por_id=None):
    """Crea o actualiza el registro de meta/venta de un asesor para un mes
    dado — mismo tienda+asesor+mes se actualiza en el mismo documento (para
    ir corrigiendo la venta del mes en curso); un mes nuevo siempre crea un
    documento nuevo, dejando los meses anteriores intactos como historial."""
    existente = get_meta_tienda(tienda, asesor_nombre, mes)
    cambios = {"actualizado_en": datetime.now().isoformat(timespec="seconds"), "actualizado_por_id": actualizado_por_id}
    if meta is not None:
        cambios["meta"] = float(meta)
    if venta_actual is not None:
        cambios["venta_actual"] = float(venta_actual)
    if existente:
        get_client().collection("metas_tienda").document(existente["id"]).update(cambios)
        return existente["id"]
    cambios.update({
        "tienda": tienda, "asesor_nombre": asesor_nombre, "mes": mes,
        "meta": float(meta) if meta is not None else 0.0,
        "venta_actual": float(venta_actual) if venta_actual is not None else 0.0,
        "creado_en": datetime.now().isoformat(timespec="seconds"),
    })
    doc_ref = get_client().collection("metas_tienda").document()
    doc_ref.set(cambios)
    return doc_ref.id


def delete_meta_tienda(meta_id):
    get_client().collection("metas_tienda").document(meta_id).delete()
