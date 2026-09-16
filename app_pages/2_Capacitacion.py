import base64
import calendar
import io
from datetime import date

import pandas as pd
import qrcode
import streamlit as st

import auth
import database as db
from config import (
    APP_URL, CAPACITACION_ARCHIVO_MAX_BYTES, CAPACITACION_ARCHIVOS_MAX, CAPACITACION_MODALIDADES,
    CAPACITACION_TIENDAS,
)
from utils import (
    archivos_a_b64_lista, archivos_lista, diploma_pdf_bytes, download_excel_button, sidebar_user_box,
    to_excel_bytes,
)

_MESES_LABEL_LARGO = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril", "05": "Mayo", "06": "Junio",
    "07": "Julio", "08": "Agosto", "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


def _label_mes_largo(anio_mes):
    if not anio_mes or "-" not in anio_mes:
        return anio_mes or "—"
    y, m = anio_mes.split("-")
    return f"{_MESES_LABEL_LARGO.get(m, m)} {y}"

user = auth.current_user()
sidebar_user_box()

st.title("🎓 Capacitación")
st.caption(
    "Módulos y submódulos de capacitación por sede, con material de apoyo y calificación "
    "del personal."
)

puede_editar = auth.puede_editar_capacitacion()

modulos_all = db.list_modulos()
submodulos_all = [sm for m in modulos_all for sm in db.list_submodulos(m["id"])]
modulos_lookup_cron = {m["id"]: m for m in modulos_all}
submods_lookup_cron = {sm["id"]: sm for sm in submodulos_all}

# ---------------------------------------------------------------------------
# Aviso de módulos con el mismo nombre: cuando dos módulos se llaman igual,
# los menús desplegables (como "Módulo" al programar una capacitación) solo
# pueden mostrar uno de los dos, y a veces terminan usando el que no tiene
# submódulos en vez del correcto — esto lo detecta y lo señala para poder
# corregirlo, en vez de dejar que confunda en silencio.
# ---------------------------------------------------------------------------
_modulos_por_nombre_norm = {}
for _m in modulos_all:
    _clave = (_m.get("nombre") or "").strip().lower()
    _modulos_por_nombre_norm.setdefault(_clave, []).append(_m)
modulos_duplicados = {k: v for k, v in _modulos_por_nombre_norm.items() if len(v) > 1}

if modulos_duplicados:
    with st.expander(
        f"⚠️ Hay {len(modulos_duplicados)} nombre(s) de módulo repetido(s) — puede causar que "
        "algunos menús elijan el módulo equivocado",
        expanded=True,
    ):
        st.caption(
            "Cuando dos módulos tienen exactamente el mismo nombre, menús como 'Módulo' al "
            "programar una capacitación a veces terminan usando el que no tiene submódulos, en "
            "vez del que sí. Para corregirlo: identifica abajo cuál de cada grupo es el que sobra "
            "(normalmente el de 0 submódulos) y elimínalo desde la pestaña '📚 Módulos', dentro de "
            "su recuadro, con «⚙️ Editar / eliminar este módulo»."
        )
        for _nombre_norm, _mods_dup in modulos_duplicados.items():
            st.markdown(f"**«{_mods_dup[0]['nombre']}»** — aparece {len(_mods_dup)} veces:")
            for _md in _mods_dup:
                _n_subs = len(db.list_submodulos(_md["id"]))
                st.caption(f"— {_n_subs} submódulo(s) · creado: {(_md.get('creado_en') or '—')[:10]}")

# ---------------------------------------------------------------------------
# Cronograma: programación mensual de capacitaciones (cuándo se imparte cada
# módulo/submódulo, a qué sede y quién la da) — independiente de las
# calificaciones, aquí solo se planea la fecha.
# ---------------------------------------------------------------------------
st.markdown("### 🗓️ Cronograma de capacitaciones")
st.caption("Programación mensual: qué capacitación se va a dar, a qué sede y cuándo.")

mes_cronograma = st.date_input(
    "Mes a consultar (elige cualquier día de ese mes)", value=date.today(), key="cap_cronograma_mes",
)
anio_mes_cronograma = mes_cronograma.strftime("%Y-%m")
st.markdown(f"##### {_label_mes_largo(anio_mes_cronograma)}")

programaciones_mes = db.list_capacitacion_programaciones(mes=anio_mes_cronograma)

tab_cron_lista, tab_cron_calendario, tab_cron_registro = st.tabs(["📋 Lista", "📅 Calendario", "🔗 Registro (QR)"])

# --------------------------------------------------------------------------
# Lista: la tabla + programar/editar/eliminar.
# --------------------------------------------------------------------------
with tab_cron_lista:
    if not programaciones_mes:
        st.caption("No hay capacitaciones programadas para este mes.")
    else:
        df_cron = pd.DataFrame([{
            "Fecha": pr.get("fecha"),
            "Módulo": (modulos_lookup_cron.get(pr.get("modulo_id")) or {}).get("nombre") or "—",
            "Submódulo": (
                (submods_lookup_cron.get(pr.get("submodulo_id")) or {}).get("nombre") or "—"
                if pr.get("submodulo_id") else "General (módulo completo)"
            ),
            "Modalidad": pr.get("modalidad") or "—",
            "Sede": pr.get("tienda") or "Todas",
            "Responsable": pr.get("responsable") or "—",
            "Link virtual": pr.get("link_virtual") or "—",
            "Notas": pr.get("notas") or "—",
        } for pr in programaciones_mes])
        st.dataframe(df_cron, use_container_width=True, hide_index=True)
        download_excel_button(df_cron, "cronograma_capacitaciones.xlsx", key="cap_cronograma_descargar_excel")

    if puede_editar:
        with st.expander("➕ Programar una capacitación"):
            if not modulos_all:
                st.caption("Primero crea al menos un módulo en la pestaña '📚 Módulos' para poder programarlo.")
            else:
                # El "Módulo" va FUERA del formulario a propósito: los campos
                # dentro de un st.form no actualizan la página hasta que se
                # presiona el botón de enviar, así que si estuviera adentro,
                # la lista de "Submódulo" se quedaría mostrando los
                # submódulos del módulo anterior hasta después de guardar.
                # Estando afuera, en cuanto cambias el Módulo, el Submódulo
                # se actualiza al instante con los submódulos correctos.
                opciones_modulo_prog = {m["nombre"]: m["id"] for m in modulos_all}
                modulo_prog_nombre = st.selectbox(
                    "Módulo", list(opciones_modulo_prog.keys()), key="cap_prog_modulo_n",
                )
                modulo_prog_id = opciones_modulo_prog[modulo_prog_nombre]
                opciones_submod_prog = {"(módulo completo)": None}
                opciones_submod_prog.update(
                    {sm["nombre"]: sm["id"] for sm in db.list_submodulos(modulo_prog_id)}
                )
                with st.form("cap_nueva_programacion", clear_on_submit=True):
                    fecha_prog_n = st.date_input(
                        "Fecha de la capacitación", value=date.today(), key="cap_prog_fecha_n",
                    )
                    submod_prog_nombre = st.selectbox(
                        "Submódulo (opcional)", list(opciones_submod_prog.keys()), key="cap_prog_submodulo_n",
                    )
                    submod_prog_id = opciones_submod_prog[submod_prog_nombre]
                    modalidad_prog = st.selectbox(
                        "Modalidad", CAPACITACION_MODALIDADES, key="cap_prog_modalidad_n",
                    )
                    tienda_prog = st.selectbox(
                        "Sede (opcional, déjalo en 'Todas' si aplica a todas)",
                        ["Todas"] + CAPACITACION_TIENDAS, key="cap_prog_tienda_n",
                    )
                    responsable_prog = st.text_input(
                        "Responsable / capacitador (opcional)", key="cap_prog_responsable_n",
                    )
                    link_virtual_prog = st.text_input(
                        "Link de la capacitación virtual (solo si es Virtual)", key="cap_prog_link_n",
                    )
                    notas_prog = st.text_area("Notas (opcional)", key="cap_prog_notas_n")
                    if st.form_submit_button("📅 Agregar al cronograma", use_container_width=True):
                        db.create_capacitacion_programacion(
                            fecha_prog_n, modulo_prog_id, submod_prog_id,
                            None if tienda_prog == "Todas" else tienda_prog,
                            responsable_prog.strip() or None, notas_prog.strip() or None, modalidad_prog,
                            link_virtual_prog.strip() or None,
                        )
                        st.success(
                            "Capacitación agregada al cronograma. En la pestaña '🔗 Registro' de "
                            "abajo puedes descargar su código QR para que el personal confirme su "
                            "asistencia."
                        )
                        st.rerun()

        if programaciones_mes:
            st.markdown("###### ✏️ Editar / eliminar una capacitación programada")
            opciones_prog_ed = {
                f"[{pr.get('fecha')}] "
                f"{(modulos_lookup_cron.get(pr.get('modulo_id')) or {}).get('nombre') or '—'}"
                + (f" · {pr.get('tienda')}" if pr.get("tienda") else ""): pr["id"]
                for pr in programaciones_mes
            }
            elegido_prog = st.selectbox(
                "Selecciona una capacitación programada", ["—"] + list(opciones_prog_ed.keys()),
                key="cap_prog_editar_select",
            )
            if elegido_prog != "—":
                prog_id_sel = opciones_prog_ed[elegido_prog]
                pr_ed = db.get_capacitacion_programacion(prog_id_sel)
                # El "Módulo" va FUERA del formulario por la misma razón que
                # en "Programar una capacitación" arriba: dentro de un
                # st.form, la lista de "Submódulo" no se actualiza hasta
                # después de guardar — aquí sí se actualiza al instante.
                opciones_modulo_ed = {m["nombre"]: m["id"] for m in modulos_all}
                modulo_actual_nombre = (modulos_lookup_cron.get(pr_ed.get("modulo_id")) or {}).get("nombre")
                modulo_prog_nombre_ed = st.selectbox(
                    "Módulo", list(opciones_modulo_ed.keys()),
                    index=list(opciones_modulo_ed.keys()).index(modulo_actual_nombre)
                    if modulo_actual_nombre in opciones_modulo_ed else 0,
                    key=f"cap_prog_modulo_ed_{prog_id_sel}",
                )
                modulo_prog_id_ed = opciones_modulo_ed[modulo_prog_nombre_ed]
                opciones_submod_ed = {"(módulo completo)": None}
                opciones_submod_ed.update(
                    {sm["nombre"]: sm["id"] for sm in db.list_submodulos(modulo_prog_id_ed)}
                )
                submod_actual_nombre = (
                    (submods_lookup_cron.get(pr_ed.get("submodulo_id")) or {}).get("nombre")
                    if pr_ed.get("submodulo_id") else "(módulo completo)"
                )
                with st.form(f"cap_editar_prog_{prog_id_sel}"):
                    fecha_prog_ed = st.date_input(
                        "Fecha", value=date.fromisoformat(pr_ed["fecha"]) if pr_ed.get("fecha") else date.today(),
                    )
                    submod_prog_nombre_ed = st.selectbox(
                        "Submódulo (opcional)", list(opciones_submod_ed.keys()),
                        index=list(opciones_submod_ed.keys()).index(submod_actual_nombre)
                        if submod_actual_nombre in opciones_submod_ed else 0,
                        key=f"cap_prog_submodulo_ed_{prog_id_sel}",
                    )
                    submod_prog_id_ed = opciones_submod_ed[submod_prog_nombre_ed]
                    modalidad_prog_ed = st.selectbox(
                        "Modalidad", CAPACITACION_MODALIDADES,
                        index=CAPACITACION_MODALIDADES.index(pr_ed["modalidad"])
                        if pr_ed.get("modalidad") in CAPACITACION_MODALIDADES else 0,
                        key=f"cap_prog_modalidad_ed_{prog_id_sel}",
                    )
                    tienda_prog_ed = st.selectbox(
                        "Sede (opcional)", ["Todas"] + CAPACITACION_TIENDAS,
                        index=(["Todas"] + CAPACITACION_TIENDAS).index(pr_ed["tienda"])
                        if pr_ed.get("tienda") in CAPACITACION_TIENDAS else 0,
                        key=f"cap_prog_tienda_ed_{prog_id_sel}",
                    )
                    responsable_prog_ed = st.text_input(
                        "Responsable / capacitador (opcional)", value=pr_ed.get("responsable") or "",
                    )
                    link_virtual_prog_ed = st.text_input(
                        "Link de la capacitación virtual (solo si es Virtual)",
                        value=pr_ed.get("link_virtual") or "",
                    )
                    notas_prog_ed = st.text_area("Notas (opcional)", value=pr_ed.get("notas") or "")
                    colp1, colp2 = st.columns(2)
                    guardar_prog = colp1.form_submit_button("💾 Guardar cambios", use_container_width=True)
                    eliminar_prog = colp2.form_submit_button(
                        "🗑️ Eliminar del cronograma", use_container_width=True,
                    )
                    if guardar_prog:
                        db.update_capacitacion_programacion(
                            prog_id_sel, fecha=str(fecha_prog_ed), modulo_id=modulo_prog_id_ed,
                            submodulo_id=submod_prog_id_ed, modalidad=modalidad_prog_ed,
                            tienda=None if tienda_prog_ed == "Todas" else tienda_prog_ed,
                            responsable=responsable_prog_ed.strip() or None,
                            link_virtual=link_virtual_prog_ed.strip() or None,
                            notas=notas_prog_ed.strip() or None,
                        )
                        st.success("Cronograma actualizado.")
                        st.rerun()
                    if eliminar_prog:
                        db.delete_capacitacion_programacion(prog_id_sel)
                        st.success("Eliminado del cronograma.")
                        st.rerun()

# --------------------------------------------------------------------------
# Calendario: cuadrícula tipo calendario de pared, un recuadro por día del
# mes, con las capacitaciones programadas ese día.
# --------------------------------------------------------------------------
with tab_cron_calendario:
    progs_por_dia = {}
    for pr in programaciones_mes:
        try:
            dia_pr = date.fromisoformat(pr["fecha"]).day
        except (ValueError, TypeError):
            continue
        progs_por_dia.setdefault(dia_pr, []).append(pr)

    hoy_cal = date.today()
    dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    header_cols = st.columns(7)
    for header_col, nombre_dia in zip(header_cols, dias_semana):
        header_col.markdown(f"<div style='text-align:center;font-weight:700;'>{nombre_dia}</div>", unsafe_allow_html=True)

    for semana in calendar.monthcalendar(mes_cronograma.year, mes_cronograma.month):
        cols_semana = st.columns(7)
        for col_dia, dia_num in zip(cols_semana, semana):
            with col_dia:
                if dia_num == 0:
                    st.markdown(
                        "<div style='min-height:78px;border-radius:6px;'></div>", unsafe_allow_html=True,
                    )
                    continue
                es_hoy = (
                    dia_num == hoy_cal.day and mes_cronograma.month == hoy_cal.month
                    and mes_cronograma.year == hoy_cal.year
                )
                fondo = "background:#fff3cd;" if es_hoy else "background:#f7f7f5;"
                progs_dia = progs_por_dia.get(dia_num, [])
                lineas_html = "".join(
                    "<div style='font-size:0.72rem;margin-top:2px;line-height:1.15;'>"
                    + ("💻 " if pr.get("modalidad") == "Virtual" else "🏢 " if pr.get("modalidad") == "Presencial" else "🎓 ")
                    + f"{(modulos_lookup_cron.get(pr.get('modulo_id')) or {}).get('nombre') or '—'}"
                    + (f"<br>&nbsp;&nbsp;· {pr['tienda']}" if pr.get("tienda") else "")
                    + "</div>"
                    for pr in progs_dia[:3]
                )
                if len(progs_dia) > 3:
                    lineas_html += (
                        f"<div style='font-size:0.68rem;color:#898781;margin-top:2px;'>"
                        f"+{len(progs_dia) - 3} más</div>"
                    )
                st.markdown(
                    f"<div style='border:1px solid #e1e0d9;border-radius:6px;padding:5px;"
                    f"min-height:78px;{fondo}'>"
                    f"<div style='font-weight:700;'>{dia_num}</div>{lineas_html}</div>",
                    unsafe_allow_html=True,
                )
    st.caption(
        "🟡 Hoy resaltado en amarillo · 💻 Virtual · 🏢 Presencial. "
        "Para editar o eliminar una capacitación, usa la pestaña «Lista»."
    )

# --------------------------------------------------------------------------
# Registro (QR): cada capacitación programada tiene su propio código QR /
# link — el personal lo escanea desde su celular, confirma su asistencia (sin
# necesidad de iniciar sesión) y, si la capacitación es virtual, ahí mismo
# recibe el link para entrar. Se genera solo, no hay que crearlo aparte: en
# cuanto la capacitación queda en el cronograma, ya tiene su QR listo.
# --------------------------------------------------------------------------
with tab_cron_registro:
    if not programaciones_mes:
        st.caption("No hay capacitaciones programadas para este mes todavía.")
    else:
        st.caption(
            "Comparte este código QR (o el link) con el personal para que confirme su asistencia "
            "desde su celular, sin necesidad de iniciar sesión. Si la capacitación es virtual, al "
            "confirmar recibe ahí mismo el link para entrar."
        )
        opciones_prog_qr = {
            f"[{pr.get('fecha')}] "
            f"{(modulos_lookup_cron.get(pr.get('modulo_id')) or {}).get('nombre') or '—'}"
            + (f" · {pr.get('tienda')}" if pr.get("tienda") else ""): pr["id"]
            for pr in programaciones_mes
        }
        elegido_prog_qr = st.selectbox(
            "Selecciona una capacitación programada", list(opciones_prog_qr.keys()), key="cap_prog_qr_select",
        )
        prog_id_qr = opciones_prog_qr[elegido_prog_qr]
        link_registro = f"{APP_URL}/?capacitacion={prog_id_qr}"

        col_qr, col_asist = st.columns([1, 1.4])
        with col_qr:
            qr_img = qrcode.make(link_registro, box_size=8, border=2)
            buf_qr = io.BytesIO()
            qr_img.save(buf_qr, format="PNG")
            png_qr = buf_qr.getvalue()
            st.image(png_qr, caption="Código QR de registro", width=220)
            st.download_button(
                "⬇️ Descargar QR (PNG)", data=png_qr, file_name=f"qr_capacitacion_{prog_id_qr}.png",
                mime="image/png", use_container_width=True, key=f"cap_qr_descargar_{prog_id_qr}",
            )
            st.code(link_registro)

        with col_asist:
            st.markdown("###### 👥 Asistencias confirmadas")
            asistencias_prog = db.list_capacitacion_asistencias(programacion_id=prog_id_qr)
            if not asistencias_prog:
                st.caption("Todavía nadie ha confirmado su asistencia con este QR.")
            else:
                df_asist_prog = pd.DataFrame([{
                    "Nombre": a["nombre"], "Sede": a.get("tienda") or "—",
                    "Confirmado": (a.get("confirmado_en") or "")[:16].replace("T", " "),
                } for a in asistencias_prog])
                st.dataframe(df_asist_prog, use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Resumen numérico rápido
# ---------------------------------------------------------------------------
personal_activo = db.list_personal_tiendas(solo_activos=True)
todas_calif = db.list_calificaciones()
promedio_general = (sum(c["calificacion"] for c in todas_calif) / len(todas_calif)) if todas_calif else 0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Módulos", len(modulos_all))
k2.metric("Submódulos", len(submodulos_all))
k3.metric("Personal activo", len(personal_activo))
k4.metric("Promedio de calificación", f"{promedio_general:.0f}" if todas_calif else "—")

st.divider()

tab_modulos, tab_personal, tab_calificaciones = st.tabs(
    ["📚 Módulos", "🏬 Personal por sede", "📝 Calificaciones"]
)

# --------------------------------------------------------------------------
# Módulos y submódulos
# --------------------------------------------------------------------------
with tab_modulos:
    if puede_editar:
        with st.expander("➕ Crear nuevo módulo"):
            with st.form("nuevo_modulo_form", clear_on_submit=True):
                nombre_mod = st.text_input("Nombre del módulo (ej. 'Ventas')")
                desc_mod = st.text_area("Descripción (opcional)")
                if st.form_submit_button("Crear módulo", use_container_width=True):
                    _nombres_existentes = {(m.get("nombre") or "").strip().lower() for m in modulos_all}
                    if not nombre_mod.strip():
                        st.error("El nombre del módulo es obligatorio.")
                    elif nombre_mod.strip().lower() in _nombres_existentes:
                        st.error(
                            f"Ya existe un módulo llamado «{nombre_mod.strip()}» — usa otro nombre, o "
                            "edita el que ya existe en vez de crear uno nuevo."
                        )
                    else:
                        db.create_modulo(nombre_mod.strip(), desc_mod.strip() or None)
                        st.success(f"Módulo '{nombre_mod}' creado.")
                        st.rerun()

    if not modulos_all:
        st.info("Todavía no hay módulos de capacitación." + (" Crea el primero arriba." if puede_editar else ""))
    else:
        for m in modulos_all:
            submods = db.list_submodulos(m["id"])
            with st.expander(f"📁 {m['nombre']} ({len(submods)} submódulo{'s' if len(submods) != 1 else ''})"):
                if m.get("descripcion"):
                    st.caption(m["descripcion"])

                if not submods:
                    st.caption("Sin submódulos todavía.")
                else:
                    for sm in submods:
                        with st.container(border=True):
                            st.markdown(f"**📂 {sm['nombre']}**")
                            if sm.get("descripcion"):
                                st.caption(sm["descripcion"])
                            archivos = archivos_lista(sm)
                            if archivos:
                                for i, a in enumerate(archivos):
                                    st.download_button(
                                        f"📎 {a['nombre']}", data=base64.b64decode(a["b64"]),
                                        file_name=a["nombre"], mime=a.get("tipo") or "application/octet-stream",
                                        use_container_width=True, key=f"cap_file_{sm['id']}_{i}",
                                    )
                            else:
                                st.caption("Sin archivos adjuntos.")

                            asistencias_sm = db.list_capacitacion_asistencias(
                                modulo_id=m["id"], submodulo_id=sm["id"],
                            )
                            with st.expander(f"👥 Asistencias registradas ({len(asistencias_sm)})"):
                                if not asistencias_sm:
                                    st.caption(
                                        "Nadie ha confirmado asistencia a una capacitación de este "
                                        "submódulo todavía."
                                    )
                                else:
                                    df_asist_sm = pd.DataFrame([{
                                        "Nombre": a["nombre"], "Sede": a.get("tienda") or "—",
                                        "Fecha": a.get("fecha") or "—",
                                    } for a in asistencias_sm])
                                    st.dataframe(df_asist_sm, use_container_width=True, hide_index=True)

                            if puede_editar:
                                editando_key = f"cap_editando_sm_{sm['id']}"
                                if st.button(
                                    "✏️ Editar / eliminar", key=f"cap_toggle_sm_{sm['id']}", use_container_width=True,
                                ):
                                    st.session_state[editando_key] = not st.session_state.get(editando_key, False)
                                    st.rerun()

                                if st.session_state.get(editando_key):
                                    with st.form(f"editar_submodulo_{sm['id']}"):
                                        nombre_sm_ed = st.text_input("Nombre del submódulo", value=sm["nombre"])
                                        desc_sm_ed = st.text_area("Descripción", value=sm.get("descripcion") or "")
                                        st.caption(
                                            f"Archivos actuales: {', '.join(a['nombre'] for a in archivos)}"
                                            if archivos else "Archivos actuales: ninguno."
                                        )
                                        nuevos_archivos = st.file_uploader(
                                            f"Reemplazar archivos (máximo {CAPACITACION_ARCHIVOS_MAX}) — "
                                            "déjalo vacío para no cambiarlos",
                                            accept_multiple_files=True, key=f"cap_reemplazar_{sm['id']}",
                                        )
                                        colf1, colf2 = st.columns(2)
                                        guardar_sm = colf1.form_submit_button("Guardar cambios", use_container_width=True)
                                        eliminar_sm = colf2.form_submit_button("Eliminar submódulo", use_container_width=True)
                                        if guardar_sm:
                                            if not nombre_sm_ed.strip():
                                                st.error("El nombre del submódulo es obligatorio.")
                                            else:
                                                update_kwargs = {
                                                    "nombre": nombre_sm_ed.strip(),
                                                    "descripcion": desc_sm_ed.strip() or None,
                                                }
                                                error_archivo = None
                                                if nuevos_archivos:
                                                    try:
                                                        update_kwargs["archivos"] = archivos_a_b64_lista(
                                                            nuevos_archivos, CAPACITACION_ARCHIVO_MAX_BYTES,
                                                            CAPACITACION_ARCHIVOS_MAX,
                                                        )
                                                    except ValueError as e:
                                                        error_archivo = str(e)
                                                if error_archivo:
                                                    st.error(error_archivo)
                                                else:
                                                    db.update_submodulo(sm["id"], **update_kwargs)
                                                    st.session_state.pop(editando_key, None)
                                                    st.success("Submódulo actualizado.")
                                                    st.rerun()
                                        if eliminar_sm:
                                            db.delete_submodulo(sm["id"])
                                            st.session_state.pop(editando_key, None)
                                            st.success("Submódulo eliminado.")
                                            st.rerun()

                st.divider()
                st.markdown("###### 👥 Asistencias — capacitaciones generales del módulo")
                st.caption(
                    "Asistencias confirmadas a capacitaciones programadas para todo el módulo "
                    "(sin un submódulo específico). Las de cada submódulo aparecen dentro de "
                    "'Asistencias registradas' en su propio recuadro, arriba."
                )
                asistencias_mod_general = [
                    a for a in db.list_capacitacion_asistencias(modulo_id=m["id"]) if not a.get("submodulo_id")
                ]
                if not asistencias_mod_general:
                    st.caption("Nadie ha confirmado asistencia todavía.")
                else:
                    df_asist_mod = pd.DataFrame([{
                        "Nombre": a["nombre"], "Sede": a.get("tienda") or "—",
                        "Fecha": a.get("fecha") or "—",
                    } for a in asistencias_mod_general])
                    st.dataframe(df_asist_mod, use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("###### 🎓 Diploma de finalización")
                if not personal_activo:
                    st.caption(
                        "No hay personal activo registrado todavía — agrégalo en la pestaña "
                        "'🏬 Personal por sede' para poder generar diplomas."
                    )
                else:
                    opciones_persona_dip = {f"{p['nombre']} ({p['tienda']})": p for p in personal_activo}
                    persona_dip_nombre = st.selectbox(
                        "Persona", list(opciones_persona_dip.keys()), key=f"cap_dip_persona_{m['id']}",
                    )
                    persona_dip = opciones_persona_dip[persona_dip_nombre]
                    diploma_existente = db.get_capacitacion_diploma(persona_dip["id"], m["id"])
                    if diploma_existente:
                        st.caption(f"✅ Módulo finalizado el {diploma_existente.get('fecha') or '—'}.")
                        st.download_button(
                            "🎓 Descargar diploma (PDF)",
                            data=diploma_pdf_bytes(
                                persona_dip["nombre"], persona_dip["tienda"], m["nombre"],
                                diploma_existente.get("fecha"),
                            ),
                            file_name=f"diploma_{persona_dip['nombre']}_{m['nombre']}.pdf".replace(" ", "_"),
                            mime="application/pdf", use_container_width=True,
                            key=f"cap_dip_descargar_{m['id']}_{persona_dip['id']}",
                        )
                    elif puede_editar:
                        if st.button(
                            "🎓 Finalizar módulo y generar diploma",
                            key=f"cap_dip_finalizar_{m['id']}_{persona_dip['id']}", use_container_width=True,
                        ):
                            db.finalizar_modulo_capacitacion(
                                persona_dip["id"], m["id"], persona_dip["tienda"], generado_por=user.get("nombre"),
                            )
                            st.success(
                                f"Módulo '{m['nombre']}' finalizado para {persona_dip['nombre']}. "
                                "Ya puedes descargar su diploma."
                            )
                            st.rerun()
                    else:
                        st.caption("Esta persona todavía no ha finalizado este módulo.")

                if puede_editar:
                    st.markdown("###### ➕ Agregar submódulo")
                    with st.form(f"nuevo_submodulo_{m['id']}", clear_on_submit=True):
                        nombre_sm = st.text_input("Nombre del submódulo (ej. 'Selling up')")
                        desc_sm = st.text_area("Descripción (opcional)")
                        archivos_subidos = st.file_uploader(
                            f"Presentación, políticas o material de apoyo (máximo {CAPACITACION_ARCHIVOS_MAX} archivos)",
                            accept_multiple_files=True, key=f"cap_nuevo_archivo_{m['id']}",
                        )
                        if st.form_submit_button("Crear submódulo", use_container_width=True):
                            if not nombre_sm.strip():
                                st.error("El nombre del submódulo es obligatorio.")
                            else:
                                try:
                                    archivos_lista_nueva = archivos_a_b64_lista(
                                        archivos_subidos, CAPACITACION_ARCHIVO_MAX_BYTES, CAPACITACION_ARCHIVOS_MAX,
                                    )
                                except ValueError as e:
                                    st.error(str(e))
                                else:
                                    db.create_submodulo(m["id"], nombre_sm.strip(), desc_sm.strip() or None, archivos_lista_nueva)
                                    st.success(f"Submódulo '{nombre_sm}' creado.")
                                    st.rerun()

                    st.divider()
                    editando_mod_key = f"cap_editando_mod_{m['id']}"
                    if st.button("⚙️ Editar / eliminar este módulo", key=f"cap_toggle_mod_{m['id']}", use_container_width=True):
                        st.session_state[editando_mod_key] = not st.session_state.get(editando_mod_key, False)
                        st.rerun()

                    if st.session_state.get(editando_mod_key):
                        with st.form(f"editar_modulo_{m['id']}"):
                            nombre_mod_ed = st.text_input("Nombre del módulo", value=m["nombre"])
                            desc_mod_ed = st.text_area("Descripción", value=m.get("descripcion") or "")
                            if st.form_submit_button("Guardar cambios", use_container_width=True):
                                _nombres_otros = {
                                    (otro.get("nombre") or "").strip().lower()
                                    for otro in modulos_all if otro["id"] != m["id"]
                                }
                                if not nombre_mod_ed.strip():
                                    st.error("El nombre del módulo es obligatorio.")
                                elif nombre_mod_ed.strip().lower() in _nombres_otros:
                                    st.error(
                                        f"Ya existe otro módulo llamado «{nombre_mod_ed.strip()}» — usa "
                                        "otro nombre."
                                    )
                                else:
                                    db.update_modulo(
                                        m["id"], nombre=nombre_mod_ed.strip(), descripcion=desc_mod_ed.strip() or None,
                                    )
                                    st.session_state.pop(editando_mod_key, None)
                                    st.success("Módulo actualizado.")
                                    st.rerun()

                        st.caption(
                            "⚠️ Eliminar el módulo también elimina todos sus submódulos, archivos y "
                            "calificaciones asociadas — no se puede deshacer."
                        )
                        confirmar_borrar_mod = st.checkbox(
                            "Confirmo que deseo eliminar este módulo por completo", key=f"cap_confirmar_del_mod_{m['id']}",
                        )
                        if st.button(
                            "🗑️ Eliminar módulo", key=f"cap_del_mod_{m['id']}", disabled=not confirmar_borrar_mod,
                        ):
                            db.delete_modulo(m["id"])
                            st.session_state.pop(editando_mod_key, None)
                            st.success("Módulo eliminado.")
                            st.rerun()

# --------------------------------------------------------------------------
# Personal por sede
# --------------------------------------------------------------------------
with tab_personal:
    if puede_editar:
        with st.expander("➕ Agregar personal"):
            with st.form("nuevo_personal_form", clear_on_submit=True):
                nombre_p = st.text_input("Nombre completo")
                c1, c2 = st.columns(2)
                tienda_p = c1.selectbox("Sede", CAPACITACION_TIENDAS)
                puesto_p = c2.text_input("Puesto (opcional)")
                if st.form_submit_button("Agregar personal", use_container_width=True):
                    if not nombre_p.strip():
                        st.error("El nombre es obligatorio.")
                    else:
                        db.create_personal_tienda(nombre_p.strip(), tienda_p, puesto_p.strip() or None)
                        st.success(f"'{nombre_p}' agregado a {tienda_p}.")
                        st.rerun()

    st.divider()
    filtro_tienda = st.selectbox(
        "Filtrar por sede", ["Todas"] + CAPACITACION_TIENDAS, key="cap_filtro_tienda_personal",
    )
    personal_lista = db.list_personal_tiendas(
        tienda=None if filtro_tienda == "Todas" else filtro_tienda, solo_activos=False,
    )
    if not personal_lista:
        st.info("No hay personal registrado con este filtro.")
    else:
        df_personal = pd.DataFrame([{
            "Nombre": p["nombre"], "Sede": p["tienda"], "Puesto": p.get("puesto") or "—",
            "Activo": "Sí" if p.get("activo", True) else "No",
        } for p in personal_lista])
        st.dataframe(df_personal, use_container_width=True, hide_index=True)
        download_excel_button(df_personal, "personal.xlsx", key="cap_descargar_personal")

        if puede_editar:
            st.markdown("#### ✏️ Editar / activar / eliminar")
            opciones_p_ed = {
                f"{p['nombre']} — {p['tienda']}" + ("" if p.get("activo", True) else " (inactivo)"): p["id"]
                for p in personal_lista
            }
            elegido_p = st.selectbox("Selecciona una persona", ["—"] + list(opciones_p_ed.keys()), key="cap_personal_editar")
            if elegido_p != "—":
                pid = opciones_p_ed[elegido_p]
                p_ed = db.get_personal_tienda(pid)
                with st.form(f"editar_personal_{pid}"):
                    nombre_p_ed = st.text_input("Nombre", value=p_ed["nombre"])
                    c1, c2 = st.columns(2)
                    tienda_p_ed = c1.selectbox(
                        "Sede", CAPACITACION_TIENDAS,
                        index=CAPACITACION_TIENDAS.index(p_ed["tienda"]) if p_ed.get("tienda") in CAPACITACION_TIENDAS else 0,
                    )
                    puesto_p_ed = c2.text_input("Puesto", value=p_ed.get("puesto") or "")
                    activo_p_ed = st.checkbox("Activo", value=p_ed.get("activo", True))
                    colf1, colf2 = st.columns(2)
                    guardar_p = colf1.form_submit_button("Guardar cambios", use_container_width=True)
                    eliminar_p = colf2.form_submit_button("Eliminar de la lista", use_container_width=True)
                    if guardar_p:
                        if not nombre_p_ed.strip():
                            st.error("El nombre es obligatorio.")
                        else:
                            db.update_personal_tienda(
                                pid, nombre=nombre_p_ed.strip(), tienda=tienda_p_ed,
                                puesto=puesto_p_ed.strip() or None, activo=activo_p_ed,
                            )
                            st.success("Actualizado.")
                            st.rerun()
                    if eliminar_p:
                        db.delete_personal_tienda(pid)
                        st.success("Eliminado de la lista.")
                        st.rerun()

# --------------------------------------------------------------------------
# Calificaciones
# --------------------------------------------------------------------------
with tab_calificaciones:
    if not personal_activo:
        st.info("Primero agrega personal en la pestaña 'Personal por sede'.")
    elif not modulos_all:
        st.info("Primero crea al menos un módulo en la pestaña 'Módulos'.")
    else:
        c1, c2 = st.columns(2)
        tienda_calif_sel = c1.selectbox("Sede", ["Todas"] + CAPACITACION_TIENDAS, key="cap_calif_tienda")
        personal_filtrado = (
            personal_activo if tienda_calif_sel == "Todas"
            else [p for p in personal_activo if p["tienda"] == tienda_calif_sel]
        )
        if not personal_filtrado:
            st.info("No hay personal activo en esta sede.")
        else:
            opciones_persona = {f"{p['nombre']} ({p['tienda']})": p["id"] for p in personal_filtrado}
            persona_nombre_sel = c2.selectbox("Persona", list(opciones_persona.keys()), key="cap_calif_persona")
            persona_id_sel = opciones_persona[persona_nombre_sel]
            persona_solo_nombre_sel = persona_nombre_sel.rsplit(" (", 1)[0]

            # -----------------------------------------------------------------
            # Medición del empleado: todas sus calificaciones (en cualquier
            # módulo), con la fecha y las horas de capacitación recibidas de
            # cada una — es el reporte que se pide al "medir" a una persona.
            # -----------------------------------------------------------------
            st.markdown(f"##### 📊 Medición de {persona_solo_nombre_sel}")
            calif_persona_medicion = db.list_calificaciones(persona_id=persona_id_sel)
            if not calif_persona_medicion:
                st.caption("Todavía no hay calificaciones registradas para esta persona.")
            else:
                modulos_lookup_medicion = {m["id"]: m for m in modulos_all}
                submods_lookup_medicion = {sm["id"]: sm for sm in submodulos_all}
                filas_medicion = []
                for c in calif_persona_medicion:
                    modulo_med = modulos_lookup_medicion.get(c.get("modulo_id"))
                    submod_med = (
                        submods_lookup_medicion.get(c.get("submodulo_id")) if c.get("submodulo_id") else None
                    )
                    filas_medicion.append({
                        "Fecha": c.get("fecha") or "—",
                        "Módulo": modulo_med["nombre"] if modulo_med else "—",
                        "Sub-Módulo": submod_med["nombre"] if submod_med else "General",
                        "Horas de capacitación recibidas": (
                            c.get("horas") if c.get("horas") not in (None, "") else "—"
                        ),
                        "Nota de Examen": c.get("calificacion"),
                    })
                df_medicion = pd.DataFrame(filas_medicion).sort_values("Fecha", ascending=False)
                st.dataframe(df_medicion, use_container_width=True, hide_index=True)
                total_horas_medicion = sum(c.get("horas") or 0 for c in calif_persona_medicion)
                st.caption(f"⏱️ Total de horas de capacitación recibidas: {total_horas_medicion:g}")
                download_excel_button(
                    df_medicion, f"medicion_{persona_solo_nombre_sel}.xlsx".replace(" ", "_"),
                    key=f"cap_medicion_excel_{persona_id_sel}",
                )

            st.divider()

            opciones_modulo = {m["nombre"]: m["id"] for m in modulos_all}
            modulo_nombre_sel = st.selectbox("Módulo", list(opciones_modulo.keys()), key="cap_calif_modulo")
            modulo_id_sel = opciones_modulo[modulo_nombre_sel]

            submods_sel = db.list_submodulos(modulo_id_sel)

            if puede_editar:
                with st.form(f"calificar_form_{persona_id_sel}_{modulo_id_sel}"):
                    calif_general_actual = db.get_calificacion(persona_id_sel, modulo_id_sel, None)
                    fecha_calif_default = date.today()
                    if calif_general_actual and calif_general_actual.get("fecha"):
                        try:
                            fecha_calif_default = date.fromisoformat(calif_general_actual["fecha"])
                        except ValueError:
                            pass
                    fecha_calif = st.date_input(
                        "Fecha de la capacitación / examen",
                        value=fecha_calif_default, key=f"cap_calif_fecha_{persona_id_sel}_{modulo_id_sel}",
                    )
                    st.caption(
                        "Esta fecha se guarda junto con cada calificación que marques abajo (general y/o "
                        "de submódulos)."
                    )
                    colg1, colg2 = st.columns(2)
                    calif_general = colg1.number_input(
                        f"Calificación general — {modulo_nombre_sel} (0-100)", min_value=0, max_value=100, step=5,
                        value=int(calif_general_actual["calificacion"]) if calif_general_actual else 0,
                        key=f"cap_calif_gen_{persona_id_sel}_{modulo_id_sel}",
                    )
                    horas_general = colg2.number_input(
                        "Horas de capacitación recibidas (general)", min_value=0.0, step=0.5, format="%.1f",
                        value=(
                            float(calif_general_actual["horas"])
                            if calif_general_actual and calif_general_actual.get("horas") else 0.0
                        ),
                        key=f"cap_calif_horas_gen_{persona_id_sel}_{modulo_id_sel}",
                    )
                    valores_sub = {}
                    horas_sub = {}
                    for sm in submods_sel:
                        calif_sm_actual = db.get_calificacion(persona_id_sel, modulo_id_sel, sm["id"])
                        cols1, cols2 = st.columns(2)
                        valores_sub[sm["id"]] = cols1.number_input(
                            f"«{sm['nombre']}» (0-100)", min_value=0, max_value=100, step=5,
                            value=int(calif_sm_actual["calificacion"]) if calif_sm_actual else 0,
                            key=f"cap_calif_sm_{persona_id_sel}_{sm['id']}",
                        )
                        horas_sub[sm["id"]] = cols2.number_input(
                            f"Horas — «{sm['nombre']}»", min_value=0.0, step=0.5, format="%.1f",
                            value=(
                                float(calif_sm_actual["horas"])
                                if calif_sm_actual and calif_sm_actual.get("horas") else 0.0
                            ),
                            key=f"cap_calif_horas_sm_{persona_id_sel}_{sm['id']}",
                        )
                    if st.form_submit_button("💾 Guardar calificaciones", use_container_width=True):
                        db.upsert_calificacion(
                            persona_id_sel, modulo_id_sel, None, calif_general,
                            horas=horas_general or None, fecha=fecha_calif,
                        )
                        for sm_id, val in valores_sub.items():
                            db.upsert_calificacion(
                                persona_id_sel, modulo_id_sel, sm_id, val,
                                horas=horas_sub.get(sm_id) or None, fecha=fecha_calif,
                            )
                        st.success(
                            f"Calificaciones de {persona_nombre_sel} guardadas para el módulo '{modulo_nombre_sel}'.",
                        )
                        st.rerun()
            else:
                st.caption("Tu rol es de solo vista: puedes consultar pero no calificar.")

            if puede_editar:
                st.divider()
                st.markdown("##### 📥 Carga masiva desde Excel")
                st.caption(
                    f"Para calificar de una vez a todo el personal en el módulo «{modulo_nombre_sel}» "
                    + (f"de {tienda_calif_sel}" if tienda_calif_sel != "Todas" else "de todas las sedes")
                    + ": descarga la plantilla de abajo, escribe las calificaciones (0 a 100) en las "
                      "columnas 'General' y de cada submódulo, y las horas de capacitación recibidas en "
                      "sus columnas '- Horas' — deja una celda vacía si no quieres cambiar ese dato — y "
                      "vuelve a subir el mismo archivo aquí. La columna 'Fecha' se aplica a todas las "
                      "calificaciones que se guarden de esa fila. No cambies la columna 'ID', ni el "
                      "filtro de Sede/Módulo de arriba antes de subirlo."
                )

                columnas_sub_nombres = [sm["nombre"] for sm in submods_sel]
                filas_plantilla = []
                for p in personal_filtrado:
                    calif_gen_p = db.get_calificacion(p["id"], modulo_id_sel, None)
                    fila_p = {
                        "ID": p["id"], "Nombre": p["nombre"], "Sede": p["tienda"], "Módulo": modulo_nombre_sel,
                        "Fecha": calif_gen_p.get("fecha") if calif_gen_p else None,
                        "General": calif_gen_p["calificacion"] if calif_gen_p else None,
                        "General - Horas": calif_gen_p.get("horas") if calif_gen_p else None,
                    }
                    for sm in submods_sel:
                        calif_sm_p = db.get_calificacion(p["id"], modulo_id_sel, sm["id"])
                        fila_p[sm["nombre"]] = calif_sm_p["calificacion"] if calif_sm_p else None
                        fila_p[f"{sm['nombre']} - Horas"] = calif_sm_p.get("horas") if calif_sm_p else None
                    filas_plantilla.append(fila_p)
                df_plantilla_calif = pd.DataFrame(filas_plantilla)

                nombre_archivo_plantilla = (
                    f"plantilla_calificaciones_{modulo_nombre_sel}".replace(" ", "_") + ".xlsx"
                )
                st.download_button(
                    f"📥 Descargar plantilla — {modulo_nombre_sel}",
                    data=to_excel_bytes(df_plantilla_calif, sheet_name="Calificaciones"),
                    file_name=nombre_archivo_plantilla,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True, key=f"cap_calif_plantilla_{modulo_id_sel}_{tienda_calif_sel}",
                )

                excel_calif_subido = st.file_uploader(
                    "Subir el Excel ya lleno con las calificaciones", type=["xlsx"],
                    key=f"cap_calif_subir_{modulo_id_sel}_{tienda_calif_sel}",
                )
                if excel_calif_subido is not None and st.button(
                    "📤 Cargar calificaciones del Excel", use_container_width=True,
                    key=f"cap_calif_cargar_{modulo_id_sel}_{tienda_calif_sel}",
                ):
                    try:
                        df_subido_calif = pd.read_excel(excel_calif_subido)
                    except Exception as e:
                        st.error(f"No se pudo leer el archivo: {e}")
                    else:
                        if "ID" not in df_subido_calif.columns:
                            st.error(
                                "El archivo no tiene la columna 'ID' — usa la plantilla que descargaste "
                                "arriba, sin quitarle columnas."
                            )
                        elif "Módulo" in df_subido_calif.columns and not (
                            df_subido_calif["Módulo"].dropna() == modulo_nombre_sel
                        ).all():
                            st.error(
                                f"Este archivo no es de «{modulo_nombre_sel}» — parece ser de otro módulo. "
                                "Selecciona el módulo correcto arriba antes de subirlo, o descarga la "
                                "plantilla de nuevo."
                            )
                        else:
                            ids_validos = {p["id"] for p in personal_filtrado}
                            columnas_calif = ["General"] + columnas_sub_nombres
                            guardadas, omitidas, filas_id_invalido = 0, 0, 0
                            for _, fila_subida in df_subido_calif.iterrows():
                                pid = fila_subida.get("ID")
                                if pd.isna(pid) or str(pid) not in ids_validos:
                                    filas_id_invalido += 1
                                    continue
                                pid = str(pid)
                                fecha_fila = None
                                if "Fecha" in df_subido_calif.columns:
                                    fecha_bruta = fila_subida.get("Fecha")
                                    if not pd.isna(fecha_bruta):
                                        try:
                                            fecha_fila = pd.to_datetime(fecha_bruta).date()
                                        except (ValueError, TypeError):
                                            fecha_fila = None
                                for columna in columnas_calif:
                                    if columna not in df_subido_calif.columns:
                                        continue
                                    valor = fila_subida.get(columna)
                                    if pd.isna(valor):
                                        continue
                                    try:
                                        valor_num = float(valor)
                                    except (TypeError, ValueError):
                                        omitidas += 1
                                        continue
                                    if not (0 <= valor_num <= 100):
                                        omitidas += 1
                                        continue
                                    submod_id_col = None if columna == "General" else next(
                                        (sm["id"] for sm in submods_sel if sm["nombre"] == columna), None,
                                    )
                                    horas_columna = f"{columna} - Horas"
                                    horas_fila = None
                                    if horas_columna in df_subido_calif.columns:
                                        horas_bruta = fila_subida.get(horas_columna)
                                        if not pd.isna(horas_bruta):
                                            try:
                                                horas_num = float(horas_bruta)
                                                if horas_num >= 0:
                                                    horas_fila = horas_num
                                            except (TypeError, ValueError):
                                                pass
                                    # Si la celda de Horas o Fecha viene vacía, se conserva el valor que
                                    # ya estuviera guardado (en vez de borrarlo) — igual que una celda de
                                    # calificación vacía tampoco cambia la nota existente.
                                    calif_previa_fila = db.get_calificacion(pid, modulo_id_sel, submod_id_col)
                                    if horas_fila is None and calif_previa_fila:
                                        horas_fila = calif_previa_fila.get("horas")
                                    fecha_final_fila = fecha_fila
                                    if fecha_final_fila is None and calif_previa_fila and calif_previa_fila.get("fecha"):
                                        try:
                                            fecha_final_fila = date.fromisoformat(calif_previa_fila["fecha"])
                                        except ValueError:
                                            fecha_final_fila = None
                                    db.upsert_calificacion(
                                        pid, modulo_id_sel, submod_id_col, round(valor_num),
                                        horas=horas_fila, fecha=fecha_final_fila,
                                    )
                                    guardadas += 1
                            mensaje_carga = f"Se guardaron {guardadas} calificación(es)."
                            if omitidas:
                                mensaje_carga += (
                                    f" Se omitieron {omitidas} celda(s) con un valor inválido "
                                    "(debe ser un número entre 0 y 100)."
                                )
                            if filas_id_invalido:
                                mensaje_carga += (
                                    f" Se omitieron {filas_id_invalido} fila(s) cuyo ID no corresponde a "
                                    "nadie en este filtro de sede."
                                )
                            st.success(mensaje_carga)
                            st.rerun()

            st.divider()

        st.markdown("##### Resumen de calificaciones registradas")
        if not todas_calif:
            st.caption("Todavía no hay calificaciones registradas.")
        else:
            personal_lookup = {p["id"]: p for p in db.list_personal_tiendas(solo_activos=False)}
            modulos_lookup = {m["id"]: m for m in modulos_all}
            submods_lookup = {sm["id"]: sm for sm in submodulos_all}
            filas_calif = []
            for c in todas_calif:
                persona_c = personal_lookup.get(c.get("persona_id"))
                modulo_c = modulos_lookup.get(c.get("modulo_id"))
                submod_c = submods_lookup.get(c.get("submodulo_id")) if c.get("submodulo_id") else None
                filas_calif.append({
                    "Persona": persona_c["nombre"] if persona_c else "—",
                    "Sede": persona_c["tienda"] if persona_c else "—",
                    "Módulo": modulo_c["nombre"] if modulo_c else "—",
                    "Submódulo": submod_c["nombre"] if submod_c else "General",
                    "Fecha": c.get("fecha") or "—",
                    "Horas de capacitación recibidas": c.get("horas") if c.get("horas") not in (None, "") else "—",
                    "Nota de Examen": c.get("calificacion"),
                    "Actualizado": c.get("actualizado_en"),
                })
            df_calif = pd.DataFrame(filas_calif).sort_values(["Persona", "Módulo", "Submódulo"])
            st.dataframe(df_calif, use_container_width=True, hide_index=True)
