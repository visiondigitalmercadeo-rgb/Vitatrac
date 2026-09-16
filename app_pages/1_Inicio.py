import streamlit as st

import auth
import database as db
from config import EMPRESA_NOMBRE
from utils import sidebar_user_box

user = auth.current_user()
sidebar_user_box()

st.title(f"🏠 Bienvenido a {EMPRESA_NOMBRE}")
st.caption("Plataforma de capacitación: módulos, cronograma, calificaciones y diplomas del personal.")

modulos = db.list_modulos()
personal = db.list_personal_tiendas(solo_activos=True)
calificaciones = db.list_calificaciones()
promedio = (sum(c["calificacion"] for c in calificaciones) / len(calificaciones)) if calificaciones else 0
programaciones_mes = db.list_capacitacion_programaciones(mes=db.mes_actual())

k1, k2, k3, k4 = st.columns(4)
k1.metric("Módulos", len(modulos))
k2.metric("Personal activo", len(personal))
k3.metric("Promedio de calificación", f"{promedio:.0f}" if calificaciones else "—")
k4.metric("Capacitaciones este mes", len(programaciones_mes))

st.divider()
st.markdown(
    "Ve a la pestaña **🎓 Capacitación** para programar capacitaciones, subir material de apoyo, "
    "registrar calificaciones y generar diplomas."
)
