"""Página pública de registro/confirmación de asistencia a una capacitación
programada: el formulario que el personal llena desde su celular al escanear
el código QR de esa capacitación. No requiere haber iniciado sesión — se
llama desde app.py ANTES de auth.require_login()."""

import streamlit as st

import database as db
from config import CAPACITACION_TIENDAS, EMPRESA_NOMBRE, LOGO_PATH

_MESES_LABEL_CORTO = {
    "01": "enero", "02": "febrero", "03": "marzo", "04": "abril", "05": "mayo", "06": "junio",
    "07": "julio", "08": "agosto", "09": "septiembre", "10": "octubre", "11": "noviembre", "12": "diciembre",
}


def _fecha_legible(fecha_iso):
    if not fecha_iso or len(fecha_iso) != 10:
        return fecha_iso or "—"
    anio, mes, dia = fecha_iso[0:4], fecha_iso[5:7], fecha_iso[8:10]
    return f"{int(dia)} de {_MESES_LABEL_CORTO.get(mes, mes)} de {anio}"


def render_registro(programacion_id):
    """Formulario público de confirmación de asistencia. Devuelve True si
    atendió la solicitud (haya que hacer st.stop() después)."""
    prog = db.get_capacitacion_programacion(programacion_id)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        try:
            st.image(LOGO_PATH, width=280)
        except Exception:
            pass

        if not prog:
            st.error(
                "Este enlace de registro ya no es válido — la capacitación pudo haber sido "
                "eliminada o reprogramada. Por favor pide un enlace nuevo a quien la organiza."
            )
            return True

        modulo = db.get_modulo(prog.get("modulo_id")) or {}
        submod = db.get_submodulo(prog["submodulo_id"]) if prog.get("submodulo_id") else None
        nombre_capacitacion = modulo.get("nombre") or "Capacitación"
        if submod:
            nombre_capacitacion += f" · {submod['nombre']}"

        if st.session_state.get("cap_reg_ok_prog") == programacion_id:
            st.success("✅ ¡Listo! Tu asistencia quedó registrada.")
            if prog.get("modalidad") == "Virtual" and (prog.get("link_virtual") or "").strip():
                st.info("Usa este enlace para entrar a la capacitación en línea:")
                st.link_button(
                    "🔗 Entrar a la capacitación virtual", prog["link_virtual"].strip(), use_container_width=True,
                )
                st.code(prog["link_virtual"].strip())
            if st.button("Registrar a otra persona", use_container_width=True):
                st.session_state.pop("cap_reg_ok_prog", None)
                st.rerun()
            return True

        st.markdown(
            f"<h3 style='text-align:center;margin-top:0.5rem;'>{EMPRESA_NOMBRE} · Capacitación</h3>"
            f"<p style='text-align:center;color:#52514e;'>Confirma tu asistencia — toma menos de "
            "un minuto.</p>",
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            st.markdown(f"**📚 {nombre_capacitacion}**")
            st.caption(f"🗓️ {_fecha_legible(prog.get('fecha'))}")
            if prog.get("modalidad"):
                icono_modalidad = "💻" if prog["modalidad"] == "Virtual" else "🏢"
                st.caption(f"{icono_modalidad} {prog['modalidad']}")
            if prog.get("tienda"):
                st.caption(f"🏬 {prog['tienda']}")

        tiendas_opciones = [prog["tienda"]] if prog.get("tienda") else CAPACITACION_TIENDAS

        with st.form("cap_registro_form"):
            nombre_reg = st.text_input("Nombre completo")
            if len(tiendas_opciones) > 1:
                tienda_reg = st.selectbox("Sede", tiendas_opciones)
            else:
                st.text_input("Sede", value=tiendas_opciones[0], disabled=True)
                tienda_reg = tiendas_opciones[0]
            confirmar_reg = st.checkbox("Confirmo mi asistencia a esta capacitación")
            enviado = st.form_submit_button("✅ Confirmar asistencia", use_container_width=True)
            if enviado:
                if not nombre_reg.strip():
                    st.error("Por favor escribe tu nombre completo.")
                elif not confirmar_reg:
                    st.error("Marca la casilla para confirmar tu asistencia antes de enviar.")
                else:
                    try:
                        db.create_capacitacion_asistencia(programacion_id, nombre_reg.strip(), tienda_reg)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.session_state["cap_reg_ok_prog"] = programacion_id
                        st.rerun()
    return True
