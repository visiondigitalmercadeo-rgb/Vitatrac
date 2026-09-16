import pandas as pd
import streamlit as st

import auth
import database as db
from config import PAGINAS_ASIGNABLES_EXTRA, PAGINAS_REGISTRO, ROLES, ROLES_LABEL
from utils import sidebar_user_box

user = auth.current_user()
sidebar_user_box()

if not auth.is_admin():
    st.error("Esta sección es solo para administradores.")
    st.stop()

st.title("👥 Administración de usuarios")
st.caption("Crear usuarios, activar/desactivar accesos y restablecer contraseñas.")

usuarios = db.list_usuarios()
etiquetas_paginas = {p["key"]: f"{p['icon']} {p['title']}" for p in PAGINAS_REGISTRO}

tab_lista, tab_nueva, tab_roles = st.tabs(["📋 Usuarios", "➕ Nuevo usuario", "🧩 Accesos por rol"])

with tab_lista:
    df = pd.DataFrame([{
        "ID": u["id"], "Nombre": u["nombre"], "Usuario": u["username"],
        "Rol": ROLES_LABEL.get(u["rol"], u["rol"]), "Activo": "Sí" if u["activo"] else "No",
    } for u in usuarios])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("#### ✏️ Gestionar usuario")
    opciones = {f"{u['nombre']} ({u['username']})": u["id"] for u in usuarios}
    elegido = st.selectbox("Selecciona un usuario", ["—"] + list(opciones.keys()))
    if elegido != "—":
        uid = opciones[elegido]
        u = next(x for x in usuarios if x["id"] == uid)
        es_unico_admin = u["rol"] == "admin" and sum(1 for x in usuarios if x["rol"] == "admin") <= 1

        st.markdown("#### 🔎 Accesos actuales de este usuario")
        paginas_base_actuales = db.get_paginas_por_rol().get(u["rol"], [])
        paginas_removidas_actuales_vista = set(u.get("paginas_removidas") or []) - {"administracion"}
        paginas_extra_actuales_vista = [
            k for k in (u.get("paginas_extra") or [])
            if k in PAGINAS_ASIGNABLES_EXTRA and k not in paginas_removidas_actuales_vista
        ]
        paginas_base_efectivas_vista = [k for k in paginas_base_actuales if k not in paginas_removidas_actuales_vista]
        if not paginas_base_efectivas_vista and not paginas_extra_actuales_vista:
            st.caption("Este usuario todavía no tiene acceso a ninguna pestaña.")
        else:
            filas_acceso_actual = [
                {"Pestaña": etiquetas_paginas.get(k, k), "Cómo lo obtiene": f"Por su rol ({ROLES_LABEL.get(u['rol'], u['rol'])})"}
                for k in paginas_base_efectivas_vista
            ] + [
                {"Pestaña": etiquetas_paginas.get(k, k), "Cómo lo obtiene": "Acceso extra"}
                for k in paginas_extra_actuales_vista
            ]
            st.caption(
                f"{len(filas_acceso_actual)} pestaña(s) en total: "
                f"{len(paginas_base_efectivas_vista)} por su rol y {len(paginas_extra_actuales_vista)} de acceso extra."
            )
            if paginas_removidas_actuales_vista:
                nombres_quitadas = ", ".join(etiquetas_paginas.get(k, k) for k in sorted(paginas_removidas_actuales_vista))
                st.caption(f"🚫 Se le quitaron {len(paginas_removidas_actuales_vista)} pestaña(s) que su rol sí incluye: {nombres_quitadas}.")
            df_acceso_actual = pd.DataFrame(filas_acceso_actual)
            st.dataframe(df_acceso_actual, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            if es_unico_admin:
                st.caption("Este es el único administrador — no puedes desactivarlo desde aquí.")
            else:
                nuevo_estado = st.toggle("Usuario activo", value=bool(u["activo"]), key=f"toggle_{uid}")
                if nuevo_estado != bool(u["activo"]):
                    db.set_usuario_activo(uid, nuevo_estado)
                    st.success("Estado actualizado.")
                    st.rerun()
        with col2:
            with st.form(f"reset_pwd_{uid}"):
                nueva_pwd = st.text_input("Nueva contraseña", type="password")
                if st.form_submit_button("Restablecer contraseña"):
                    if len(nueva_pwd) < 4:
                        st.error("La contraseña debe tener al menos 4 caracteres.")
                    else:
                        db.reset_password(uid, nueva_pwd)
                        st.success("Contraseña actualizada.")

        st.markdown("#### ✏️ Editar usuario")
        with st.form(f"editar_usuario_{uid}"):
            nombre_ed = st.text_input("Nombre completo", value=u["nombre"] or "")
            username_ed = st.text_input("Usuario (para iniciar sesión)", value=u["username"] or "")
            if es_unico_admin:
                st.caption("Este es el único administrador, así que su rol no se puede cambiar aquí.")
                rol_ed = "admin"
            else:
                rol_ed = st.selectbox(
                    "Rol", ROLES, index=ROLES.index(u["rol"]) if u["rol"] in ROLES else 0,
                    format_func=lambda r: ROLES_LABEL.get(r, r),
                )
            if st.form_submit_button("Guardar cambios", use_container_width=True):
                username_norm = username_ed.strip().lower()
                if not nombre_ed.strip() or not username_norm:
                    st.error("Completa nombre y usuario.")
                else:
                    existente = db.get_user_by_username(username_norm)
                    if existente and existente["id"] != uid:
                        st.error("Ese nombre de usuario ya lo usa otra persona.")
                    else:
                        db.update_usuario(uid, nombre=nombre_ed.strip(), username=username_norm, rol=rol_ed)
                        st.success("Usuario actualizado.")
                        st.rerun()

        st.markdown("#### 🔐 Accesos de este usuario")
        st.caption(
            "Marca exactamente qué pestañas debe ver este usuario — puedes agregar pestañas que su "
            "rol no le da por defecto, o QUITAR pestañas que su rol sí le daría. Ya vienen marcadas "
            "las que tiene ahora mismo. El usuario debe cerrar sesión y volver a entrar para que el "
            "cambio se vea reflejado."
        )
        base_rol_usuario = db.get_paginas_por_rol().get(u["rol"], [])
        removidas_actuales = set(u.get("paginas_removidas") or [])
        efectivas_actuales = [
            k for k in PAGINAS_ASIGNABLES_EXTRA
            if (k in base_rol_usuario or k in (u.get("paginas_extra") or [])) and k not in removidas_actuales
        ]
        with st.form(f"accesos_usuario_{uid}"):
            seleccion_accesos = st.multiselect(
                "Pestañas que debe tener este usuario", PAGINAS_ASIGNABLES_EXTRA, default=efectivas_actuales,
                format_func=lambda k: etiquetas_paginas.get(k, k),
            )
            if st.form_submit_button("💾 Guardar accesos", use_container_width=True):
                nuevas_extra = [k for k in seleccion_accesos if k not in base_rol_usuario]
                nuevas_removidas = [k for k in base_rol_usuario if k not in seleccion_accesos]
                db.update_usuario(uid, paginas_extra=nuevas_extra, paginas_removidas=nuevas_removidas)
                st.success("Accesos actualizados.")
                st.rerun()

        st.markdown("#### 🗑️ Eliminar usuario")
        st.caption(
            "Esto borra el acceso de este usuario por completo (no se puede deshacer). Sus "
            "calificaciones y diplomas generados no se eliminan."
        )
        if uid == user["id"]:
            st.info("No puedes eliminar tu propio usuario mientras tienes la sesión iniciada con él.")
        elif es_unico_admin:
            st.info("Este es el único administrador de la plataforma, no se puede eliminar.")
        else:
            with st.form(f"eliminar_usuario_{uid}"):
                confirmar = st.text_input(
                    f"Escribe el usuario **{u['username']}** para confirmar que deseas eliminarlo"
                )
                if st.form_submit_button("Eliminar definitivamente", use_container_width=True):
                    if confirmar.strip() != u["username"]:
                        st.error("El texto no coincide con el nombre de usuario. No se eliminó nada.")
                    else:
                        db.delete_usuario(uid)
                        st.success(f"Usuario '{u['username']}' eliminado.")
                        st.rerun()

with tab_nueva:
    with st.form("nuevo_usuario_form", clear_on_submit=True):
        nombre = st.text_input("Nombre completo")
        username = st.text_input("Usuario (para iniciar sesión)")
        password = st.text_input("Contraseña", type="password")
        rol = st.selectbox("Rol", ROLES, format_func=lambda r: ROLES_LABEL.get(r, r))
        paginas_extra_nuevo = st.multiselect(
            "Acceso extra a otras pestañas (opcional, además de lo que ya da el rol elegido)",
            PAGINAS_ASIGNABLES_EXTRA, format_func=lambda k: etiquetas_paginas.get(k, k),
        )
        if st.form_submit_button("Crear usuario", use_container_width=True):
            if not nombre.strip() or not username.strip() or len(password) < 4:
                st.error("Completa nombre, usuario y una contraseña de al menos 4 caracteres.")
            elif db.get_user_by_username(username.strip().lower()):
                st.error("Ese nombre de usuario ya existe.")
            else:
                db.create_usuario(
                    nombre.strip(), username.strip().lower(), password, rol, paginas_extra=paginas_extra_nuevo,
                )
                st.success(f"Usuario '{username}' creado como {ROLES_LABEL.get(rol, rol)}.")
                st.rerun()

with tab_roles:
    st.caption(
        "Define qué pestañas ve **cada rol por defecto** — el cambio aplica de inmediato a todos los "
        "usuarios de ese rol (excepto a quien ya tenga un acceso individual distinto guardado en "
        "'🔐 Accesos de este usuario', dentro de la pestaña '📋 Usuarios'). 'Administración de usuarios' "
        "es exclusiva del rol Administrador y no se puede quitar ni asignar a otro rol desde aquí."
    )
    paginas_por_rol_actual = db.get_paginas_por_rol()
    rol_elegido = st.selectbox(
        "Rol", ROLES, format_func=lambda r: ROLES_LABEL.get(r, r), key="admin_rol_paginas_sel",
    )
    cantidad_usuarios_rol = sum(1 for x in usuarios if x["rol"] == rol_elegido)
    st.caption(
        f"{cantidad_usuarios_rol} usuario(s) tienen actualmente el rol "
        f"'{ROLES_LABEL.get(rol_elegido, rol_elegido)}'."
    )
    if rol_elegido == "admin":
        st.caption("🔒 El rol Administrador siempre incluye 'Administración de usuarios', aunque no aparezca abajo.")
    paginas_actuales_rol = [k for k in paginas_por_rol_actual.get(rol_elegido, []) if k in PAGINAS_ASIGNABLES_EXTRA]
    with st.form(f"form_paginas_rol_{rol_elegido}"):
        seleccion_rol = st.multiselect(
            "Pestañas por defecto para este rol", PAGINAS_ASIGNABLES_EXTRA, default=paginas_actuales_rol,
            format_func=lambda k: etiquetas_paginas.get(k, k), key=f"ms_paginas_rol_{rol_elegido}",
        )
        if st.form_submit_button("💾 Guardar para este rol", use_container_width=True):
            paginas_a_guardar = seleccion_rol + (["administracion"] if rol_elegido == "admin" else [])
            db.set_paginas_rol(rol_elegido, paginas_a_guardar)
            st.success(f"Pestañas por defecto de '{ROLES_LABEL.get(rol_elegido, rol_elegido)}' actualizadas.")
            st.rerun()
