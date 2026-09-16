import base64
import io

import pandas as pd
import streamlit as st
from fpdf import FPDF

import auth
from config import EMPRESA_NOMBRE, FIRMA_NOMBRE, FIRMA_PATH, FIRMA_PUESTO, LOGO_PATH, ROLES_LABEL


def sidebar_user_box():
    u = auth.current_user()
    with st.sidebar:
        # Botón de refrescar datos, justo debajo del logo. Solo vuelve a
        # ejecutar la página actual (st.rerun) — NO recarga el navegador, así
        # que la sesión (usuario ya logueado) se mantiene y no manda de
        # regreso a la pantalla de credenciales.
        _, col_refrescar = st.columns([5, 1])
        with col_refrescar:
            if st.button("🔄", key="btn_refrescar_datos", help="Actualizar datos (no cierra tu sesión)"):
                st.rerun()

        st.markdown("---")
        st.caption(f"Sesión: **{u['nombre']}**  \nRol: *{ROLES_LABEL.get(u['rol'], u['rol'])}*")
        if st.button("Cerrar sesión", use_container_width=True):
            auth.do_logout()
            st.rerun()


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Datos") -> bytes:
    """Convierte un DataFrame a los bytes de un archivo .xlsx en memoria."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return buffer.getvalue()


def download_excel_button(df: pd.DataFrame, filename: str, key: str,
                           label: str = "⬇️ Descargar Excel", sheet_name: str = "Datos"):
    st.download_button(
        label, data=to_excel_bytes(df, sheet_name=sheet_name), file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, key=key,
    )


# Firestore rechaza de golpe cualquier documento que pese más de 1 MiB
# (1,048,576 bytes) en total — TODOS sus campos juntos. Cada archivo se
# guarda como texto base64 dentro del documento, y ese texto pesa ~33% más
# que el archivo original (4 bytes de base64 por cada 3 bytes reales). Este
# techo de seguridad deja margen de sobra para el resto de los campos del
# documento.
LIMITE_B64_SEGURO_POR_LLAMADA = 450_000  # bytes de texto base64 YA codificado


def _validar_limite_b64_seguro(bytes_b64_totales):
    if bytes_b64_totales > LIMITE_B64_SEGURO_POR_LLAMADA:
        raise ValueError(
            "Lo que quieres subir pesa demasiado para guardarse junto con el resto de la información "
            "de este registro (Firestore, la base de datos, tiene un límite duro de tamaño por "
            "registro). Sube un archivo más pequeño o comprime el PDF, o si son varios, súbelos en "
            "tandas más chicas. Si conectas Firebase Storage (ver README) este límite deja de aplicar."
        )


def archivos_a_b64_lista(archivos_subidos, max_bytes, max_archivos=3):
    """Convierte una lista de archivos subidos con
    st.file_uploader(accept_multiple_files=True) a una lista de
    {"nombre", "tipo", "b64"}. Retorna [] si no hay archivos. Lanza ValueError
    si se suben más de max_archivos, si alguno pesa más de max_bytes, o si el
    total ya codificado en base64 pasa el techo de seguridad de Firestore."""
    archivos_subidos = archivos_subidos or []
    if len(archivos_subidos) > max_archivos:
        raise ValueError(
            f"Puedes adjuntar máximo {max_archivos} archivos (subiste {len(archivos_subidos)}). "
            "Quita alguno e intenta de nuevo."
        )
    resultado = []
    total_b64 = 0
    for archivo in archivos_subidos:
        datos = archivo.getvalue()
        if len(datos) > max_bytes:
            raise ValueError(
                f"El archivo '{archivo.name}' pesa {len(datos) / 1000:.0f} KB; el máximo permitido "
                f"por archivo es {max_bytes / 1000:.0f} KB. Comprime el archivo e intenta de nuevo."
            )
        b64 = base64.b64encode(datos).decode("ascii")
        total_b64 += len(b64)
        resultado.append({"nombre": archivo.name, "tipo": archivo.type, "b64": b64})
    _validar_limite_b64_seguro(total_b64)
    return resultado


def archivos_lista(d: dict) -> list:
    """Normaliza los archivos adjuntos de un submódulo: solo soporta el
    formato de lista 'archivos' (ver create_submodulo/update_submodulo en
    database.py)."""
    return d.get("archivos") or []


def _pdf_safe(texto):
    return str(texto).encode("latin-1", "replace").decode("latin-1")


def _tamano_ajustado(pdf, texto, familia, estilo, ancho_max, tam_inicial, tam_minimo):
    """Reduce el tamaño de fuente hasta que 'texto' quepa en 'ancho_max' (mm),
    sin bajar de 'tam_minimo' — para que un nombre o módulo largo no se salga
    del diploma en vez de recortarse a la mitad."""
    tam = tam_inicial
    while tam > tam_minimo:
        pdf.set_font(familia, estilo, tam)
        if pdf.get_string_width(texto) <= ancho_max:
            break
        tam -= 1
    pdf.set_font(familia, estilo, tam)
    return tam


def diploma_pdf_bytes(persona_nombre: str, tienda: str, modulo_nombre: str, fecha) -> bytes:
    """Genera el PDF del diploma de finalización de un módulo de Capacitación
    (hoja horizontal tipo certificado): logo, nombre de la persona, sede,
    módulo completado, fecha, y la firma configurada en config.py (si existe)
    al calce. 'fecha' puede ser un date o un string 'YYYY-MM-DD'."""
    ROSA = (255, 12, 130)

    fecha_txt = str(fecha)
    if len(fecha_txt) == 10 and fecha_txt[4] == "-":
        fecha_txt = f"{fecha_txt[8:10]}/{fecha_txt[5:7]}/{fecha_txt[0:4]}"

    pdf = FPDF(orientation="L", format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    ancho, alto = 279.4, 215.9  # Letter horizontal, en mm

    # -- Fondo y marco decorativo --------------------------------------------
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, ancho, alto, style="F")
    pdf.set_draw_color(*ROSA)
    pdf.set_line_width(2.2)
    pdf.rect(8, 8, ancho - 16, alto - 16)
    pdf.set_draw_color(20, 20, 20)
    pdf.set_line_width(0.4)
    pdf.rect(12.5, 12.5, ancho - 25, alto - 25)
    pdf.set_line_width(0.2)

    # -- Logo, centrado arriba ---------------------------------------------
    try:
        logo_w = 50
        logo_h = logo_w * 0.5135
        pdf.image(LOGO_PATH, x=(ancho - logo_w) / 2, y=14, w=logo_w)
        y_cursor = 14 + logo_h + 7
    except Exception:
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(20, 20, 20)
        pdf.set_xy(0, 22)
        pdf.cell(ancho, 10, _pdf_safe(EMPRESA_NOMBRE), align="C")
        y_cursor = 40

    # -- Título -----------------------------------------------------------------
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_xy(0, y_cursor)
    pdf.cell(ancho, 14, _pdf_safe("DIPLOMA DE FINALIZACIÓN"), align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(0, y_cursor + 13)
    pdf.cell(ancho, 8, _pdf_safe(f"Programa de Capacitación - {EMPRESA_NOMBRE}"), align="C")

    # -- "Se otorga a" + nombre de la persona ------------------------------------
    pdf.set_text_color(90, 90, 90)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(0, y_cursor + 30)
    pdf.cell(ancho, 8, _pdf_safe("Se otorga el presente reconocimiento a"), align="C")

    pdf.set_text_color(*ROSA)
    nombre_txt = _pdf_safe(persona_nombre or "—")
    _tamano_ajustado(pdf, nombre_txt, "Times", "BI", ancho - 40, 34, 14)
    pdf.set_xy(0, y_cursor + 39)
    pdf.cell(ancho, 16, nombre_txt, align="C")

    # -- Texto de logro + módulo --------------------------------------------------
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(0, y_cursor + 58)
    pdf.cell(
        ancho, 7,
        _pdf_safe("por haber completado satisfactoriamente el módulo de capacitación"), align="C",
    )

    pdf.set_text_color(20, 20, 20)
    modulo_txt = _pdf_safe(f"«{modulo_nombre or '—'}»")
    _tamano_ajustado(pdf, modulo_txt, "Helvetica", "B", ancho - 40, 18, 11)
    pdf.set_xy(0, y_cursor + 67)
    pdf.cell(ancho, 10, modulo_txt, align="C")

    pdf.set_text_color(90, 90, 90)
    pdf.set_font("Helvetica", "I", 11)
    pdf.set_xy(0, y_cursor + 79)
    pdf.cell(ancho, 7, _pdf_safe(f"Sede: {tienda or '—'}"), align="C")

    # -- Firma y fecha, al calce --------------------------------------------------
    firmas_y = alto - 42
    # Izquierda: fecha
    pdf.set_draw_color(120, 120, 120)
    pdf.line(38, firmas_y, 118, firmas_y)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(38, firmas_y + 2)
    pdf.cell(80, 6, _pdf_safe(fecha_txt or "—"), align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(38, firmas_y + 8)
    pdf.cell(80, 5, _pdf_safe("Fecha de finalización"), align="C")

    # Derecha: firma (si existe FIRMA_PATH) + nombre y puesto configurados en
    # config.py — si el archivo de firma no existe todavía, simplemente se
    # omite la imagen y queda la línea con el nombre/puesto de texto.
    try:
        firma_w = 46
        pdf.image(FIRMA_PATH, x=161 + (80 - firma_w) / 2, y=firmas_y - 18, w=firma_w)
    except Exception:
        pass
    pdf.set_draw_color(120, 120, 120)
    pdf.line(161, firmas_y, 241, firmas_y)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(161, firmas_y + 2)
    pdf.cell(80, 6, _pdf_safe(FIRMA_NOMBRE), align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(161, firmas_y + 8)
    pdf.cell(80, 5, _pdf_safe(FIRMA_PUESTO), align="C")

    return bytes(pdf.output())
