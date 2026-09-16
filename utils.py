import base64
import hashlib
import html
import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF

import auth
import database as db
from config import (
    CATEGORICAL, EMPRESA_DIRECCION_LINEA1, EMPRESA_DIRECCION_LINEA2, EMPRESA_NOMBRE, FIRMA_ENVIO_NOMBRE,
    FIRMA_ENVIO_PATH, FIRMA_ENVIO_PUESTO, FIRMA_STEVEN_NOMBRE, FIRMA_STEVEN_PATH, FIRMA_STEVEN_PUESTO, GRIDLINE,
    INK_MUTED, INK_PRIMARY, LOGO_PATH, ROLES_LABEL, SURFACE,
)


def money(v):
    try:
        return f"Q {float(v):,.2f}"
    except (TypeError, ValueError):
        return "Q 0.00"


def scope_vendedor_id():
    """Para un vendedor, retorna su propio id (los datos se filtran a lo suyo).
    Para admin/vista, retorna None (ven todo, con selector opcional)."""
    u = auth.current_user()
    if u["rol"] == "vendedor":
        return u["id"]
    return None


def vendedor_filter_selector(label="Vendedor", key="vendedor_filter"):
    """Selector de vendedor para admin/vista. Devuelve el id elegido o None (todos)."""
    u = auth.current_user()
    if u["rol"] == "vendedor":
        return u["id"]
    vendedores = db.list_vendedores(solo_activos=False)
    opciones = {"Todos": None}
    opciones.update({v["nombre"]: v["id"] for v in vendedores})
    elegido = st.selectbox(label, list(opciones.keys()), key=key)
    return opciones[elegido]


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


def base_layout(fig: go.Figure, title=None, height=380):
    # El título usa yref="container" (relativo a toda la figura) por defecto
    # en Plotly, mientras que la leyenda por defecto usa yref="paper"
    # (relativo solo al área de la gráfica) — con poco margen superior, esas
    # dos referencias distintas terminaban superponiéndose visualmente. Aquí
    # se fija la leyenda también a yref="container" y se coloca explícitamente
    # debajo del título, con margen de sobra para ambos.
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", y=0.97, yanchor="top", font=dict(size=16)) if title else None,
        height=height,
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
        font=dict(color=INK_PRIMARY, family="system-ui, -apple-system, Segoe UI, sans-serif"),
        legend=dict(
            orientation="h", yref="container", yanchor="top",
            y=0.84 if title else 0.97, xanchor="left", x=0,
        ),
        margin=dict(l=10, r=10, t=95 if title else 40, b=10),
        colorway=CATEGORICAL,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRIDLINE, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(showgrid=True, gridcolor=GRIDLINE, tickfont=dict(color=INK_MUTED), zeroline=False)
    return fig


def df_or_empty(rows, columns=None):
    if not rows:
        return pd.DataFrame(columns=columns or [])
    return pd.DataFrame(rows)


def today_str():
    return str(date.today())


def as_lineas_venta(value):
    """Normaliza el campo 'linea_venta': acepta datos viejos (texto único) o
    nuevos (lista de productos seleccionados) y siempre retorna una lista."""
    if isinstance(value, list):
        return [v for v in value if v]
    if value:
        return [value]
    return []


def lineas_venta_display(value):
    """Texto legible (separado por comas) para mostrar en tablas/reportes."""
    return ", ".join(as_lineas_venta(value)) or "—"


def hora_24_a_12(hhmm):
    """Convierte 'HH:MM' (24 horas) a (hora_1_12, minuto, 'AM'/'PM')."""
    from datetime import datetime as _dt
    try:
        t = _dt.strptime(hhmm, "%H:%M")
    except (ValueError, TypeError):
        t = _dt.now()
    hora12 = t.hour % 12
    hora12 = 12 if hora12 == 0 else hora12
    ampm = "PM" if t.hour >= 12 else "AM"
    return hora12, t.minute, ampm


def hora_12_a_24(hora12, minuto, ampm):
    """Convierte (hora_1_12, minuto, 'AM'/'PM') a texto 'HH:MM' (24 horas)."""
    h = hora12 % 12
    if ampm == "PM":
        h += 12
    return f"{h:02d}:{minuto:02d}"


def hora_legible(iso_ts):
    """'2026-08-25T09:14:32' -> '09:14 a.m.'. Devuelve '—' si no hay valor."""
    if not iso_ts:
        return "—"
    from datetime import datetime as _dt
    try:
        t = _dt.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return "—"
    hora12 = t.hour % 12
    hora12 = 12 if hora12 == 0 else hora12
    ampm = "a.m." if t.hour < 12 else "p.m."
    return f"{hora12:02d}:{t.minute:02d} {ampm}"


def minutos_entre(inicio_iso, fin_iso=None):
    """Minutos transcurridos entre dos timestamps ISO ('...T09:14:32'). Si no
    hay fin_iso, usa la hora actual de Guatemala (para tickets todavía en
    curso — los timestamps se guardan en hora de Guatemala, así que la hora
    actual con la que se comparan debe ser la misma). Devuelve None si
    inicio_iso no existe todavía (esa etapa no ha comenzado)."""
    if not inicio_iso:
        return None
    from datetime import datetime as _dt
    try:
        inicio = _dt.fromisoformat(inicio_iso)
        fin = _dt.fromisoformat(fin_iso) if fin_iso else db.ahora_guatemala()
    except (ValueError, TypeError):
        return None
    return max(0, int((fin - inicio).total_seconds() // 60))


def minutos_legible(minutos):
    """int -> '7 min' o '1 h 12 min'. None -> '—'."""
    if minutos is None:
        return "—"
    if minutos < 60:
        return f"{minutos} min"
    h, m = divmod(minutos, 60)
    return f"{h} h {m} min"


def duracion_legible(minutos):
    """int -> '7 min', '3 h 20 min', o ya pasando de 24 horas, en días:
    '2 días 4 h'. None -> '—'. A diferencia de minutos_legible (que se usa
    en Diseño Gráfico y Tickets Tienda y no se toca), esta se usa donde el
    tiempo puede acumular varios días — como los KPIs de Mantenimiento de
    Tiendas — para que no se vea como '1500 min' o un número de horas
    gigante, sino que cambie a días automáticamente pasando las 24 horas."""
    if minutos is None:
        return "—"
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 1440:
        h, m = divmod(minutos, 60)
        return f"{h} h {m} min"
    dias, resto = divmod(minutos, 1440)
    h, _ = divmod(resto, 60)
    texto = f"{dias} día{'s' if dias != 1 else ''}"
    if h:
        texto += f" {h} h"
    return texto


def mant_tienda_historial_o_reconstruido(row):
    """Historial de etapas de una solicitud de Mantenimiento de Tiendas —
    usa 'historial_etapas' si ya existe (ver database.avanzar_mant_tienda,
    que agrega una entrada cada vez que la solicitud entra a una columna
    nueva, desde que se agregó este campo en adelante). Si la solicitud es
    de antes de que existiera ese campo, lo reconstruye lo mejor posible a
    partir de los campos anteriores (creado_en, tipo_solicitud_inicial,
    fecha_cotizacion, fecha_en_proceso, fecha_finalizado) — esa
    reconstrucción asume que la solicitud siguió el camino normal sin
    saltos ni retrocesos, así que puede quedar incompleta para casos raros,
    pero nunca falla (en el peor caso retorna una lista corta o vacía)."""
    historial = row.get("historial_etapas")
    if historial:
        return historial
    entradas = []
    tipo_inicial = row.get("tipo_solicitud_inicial") or (
        row.get("estado") if row.get("estado") in ("Lista de tareas", "Emergencia") else None
    )
    if tipo_inicial and row.get("creado_en"):
        entradas.append({"estado": tipo_inicial, "entrada_en": row["creado_en"]})
    if row.get("fecha_cotizacion"):
        entradas.append({"estado": "En cotización", "entrada_en": row["fecha_cotizacion"]})
    if row.get("fecha_en_proceso"):
        entradas.append({"estado": "En proceso", "entrada_en": row["fecha_en_proceso"]})
    if row.get("fecha_finalizado"):
        entradas.append({"estado": "Finalizado", "entrada_en": row["fecha_finalizado"]})
    return entradas


def mant_tienda_segmentos_etapa(row):
    """A partir del historial de etapas de una solicitud de Mantenimiento de
    Tiendas (ver mant_tienda_historial_o_reconstruido), retorna una lista de
    tuplas (etapa, minutos, en_curso) — una por cada vez que la solicitud
    entró a una columna. 'en_curso' es True solo para el último tramo, y
    solo si la solicitud sigue en esa columna ahora mismo (en ese caso mide
    desde que entró hasta la hora actual, en vez de hasta la siguiente
    entrada, que todavía no existe); la columna terminal 'Finalizado' nunca
    se marca 'en_curso' (no tiene sentido medir cuánto lleva finalizada)."""
    historial = mant_tienda_historial_o_reconstruido(row)
    segmentos = []
    for i, entrada in enumerate(historial):
        estado_etapa = entrada.get("estado")
        siguiente = historial[i + 1] if i + 1 < len(historial) else None
        if siguiente is not None:
            minutos = minutos_entre(entrada.get("entrada_en"), siguiente.get("entrada_en"))
            en_curso = False
        elif estado_etapa == "Finalizado":
            continue
        else:
            minutos = minutos_entre(entrada.get("entrada_en"))
            en_curso = True
        if minutos is not None:
            segmentos.append((estado_etapa, minutos, en_curso))
    return segmentos


def mant_tienda_tiempo_en_etapa(row, etapa):
    """Suma de minutos que una solicitud de Mantenimiento de Tiendas estuvo
    en una etapa dada, sumando todas las veces que pasó por ahí (por si se
    movió hacia atrás y volvió a entrar) — solo cuenta tramos YA
    COMPLETADOS; si la solicitud está actualmente en esa columna, ese tramo
    en curso no se incluye aquí (ver mant_tienda_segmentos_etapa). None si
    nunca completó un tramo en esa etapa."""
    minutos = [m for (est, m, en_curso) in mant_tienda_segmentos_etapa(row) if est == etapa and not en_curso]
    return sum(minutos) if minutos else None


def selector_hora(label_prefix, key_prefix, hora12=12, minuto=0, ampm="AM"):
    """Muestra 3 selectores (Hora 1-12 / Minuto / AM-PM) y retorna el texto
    'HH:MM' en formato 24 horas, listo para guardar en la base de datos."""
    c1, c2, c3 = st.columns(3)
    hora_sel = c1.selectbox(
        f"{label_prefix} (hora)", list(range(1, 13)),
        index=list(range(1, 13)).index(hora12), key=f"{key_prefix}_hora",
    )
    minutos_opciones = list(range(0, 60))
    minuto_sel = c2.selectbox(
        f"{label_prefix} (minutos)", minutos_opciones,
        index=minutos_opciones.index(minuto), format_func=lambda m: f"{m:02d}",
        key=f"{key_prefix}_minuto",
    )
    ampm_sel = c3.selectbox(
        f"{label_prefix} (AM/PM)", ["AM", "PM"],
        index=["AM", "PM"].index(ampm), key=f"{key_prefix}_ampm",
    )
    return hora_12_a_24(hora_sel, minuto_sel, ampm_sel)


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Datos") -> bytes:
    """Convierte un DataFrame a los bytes de un archivo .xlsx en memoria."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return buffer.getvalue()


def download_excel_button(df: pd.DataFrame, filename: str, key: str,
                           label: str = "⬇️ Descargar Excel", sheet_name: str = "Datos"):
    """Botón para descargar un DataFrame como archivo Excel (.xlsx). Disponible
    para cualquier rol que pueda ver la tabla correspondiente (vendedor, mercadeo,
    administrador, etc.) — solo exporta lo que ya está filtrado en pantalla."""
    st.download_button(
        label, data=to_excel_bytes(df, sheet_name=sheet_name), file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, key=key,
    )


def plantilla_catalogo_tecnico_bytes() -> bytes:
    """Genera en memoria la plantilla de Excel para la carga masiva del
    catálogo de máquinas y papel del Cotizador Técnico — dos hojas
    ('Máquinas' y 'Papel'), con encabezados, una fila de ejemplo y filas en
    blanco. Las mismas columnas que espera db.bulk_upsert_tecnico_maquinas /
    bulk_upsert_tecnico_papeles."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0B0B2B")
    example_font = Font(name="Arial", size=11, italic=True, color="7A6A4A")
    example_fill = PatternFill("solid", fgColor="FFF6E5")
    normal_font = Font(name="Arial", size=11)

    def _hoja(ws, encabezados, ejemplo, anchos, filas_vacias=60):
        ws.sheet_view.showGridLines = False
        for c, titulo in enumerate(encabezados, start=1):
            celda = ws.cell(row=1, column=c, value=titulo)
            celda.font = header_font
            celda.fill = header_fill
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 32
        for c, valor in enumerate(ejemplo, start=1):
            celda = ws.cell(row=2, column=c, value=valor)
            celda.font = example_font
            celda.fill = example_fill
        ws.cell(row=2, column=len(encabezados) + 1, value="← EJEMPLO: bórralo antes de subir").font = example_font
        for r in range(3, 3 + filas_vacias):
            for c in range(1, len(encabezados) + 1):
                ws.cell(row=r, column=c).font = normal_font
        for c, ancho in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(c)].width = ancho
        ws.freeze_panes = "A3"

    ws_maq = wb.active
    ws_maq.title = "Máquinas"
    _hoja(
        ws_maq,
        ["Nombre de la máquina", "Ancho máximo del pliego (cm)", "Alto máximo del pliego (cm)",
         "Costo por millar de pasadas (Q)", "Costo por plancha (Q)"],
        ["Offset 65x90 - Máquina 1", 65, 90, 350.00, 45.00],
        [28, 24, 22, 26, 20],
    )
    ws_pap = wb.create_sheet("Papel")
    _hoja(
        ws_pap,
        ["Tipo de papel", "Fabricante", "Gramaje (g/m²)", "Ancho del pliego (cm)",
         "Alto del pliego (cm)", "Costo por pliego (Q)"],
        ["Couché brillante", "Genérico", 115, 65, 90, 2.10],
        [22, 20, 16, 20, 20, 20],
    )
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# Firestore rechaza de golpe (google.api_core.exceptions.InvalidArgument, sin
# mensaje claro para el usuario) cualquier documento que pese más de 1 MiB
# (1,048,576 bytes) en total — TODOS sus campos juntos. Cada archivo se
# guarda como texto base64 dentro del documento, y ese texto pesa ~33% más
# que el archivo original (4 bytes de base64 por cada 3 bytes reales). Un
# límite "por archivo" que no toma esto en cuenta (o que no revisa el total
# cuando hay varios archivos, o varios campos con archivos, en el MISMO
# documento — ver p. ej. Mant. Tiendas: "fotos" + "cotizacion_pdfs" juntos)
# puede dejar pasar una subida que, ya codificada, no cabe — y ahí revienta
# con un error de Firestore feo en vez de avisarle a la persona. Este techo
# de seguridad se aplica DENTRO de archivo_a_b64/archivos_a_b64_lista para
# que TODA la plataforma quede protegida sin tener que revisar cada pestaña
# una por una — dejando margen de sobra para el resto de los campos del
# documento (fecha, descripción, historial, etc.) y para que quepan dos
# campos de archivos en el mismo documento sin pasarse.
LIMITE_B64_SEGURO_POR_LLAMADA = 450_000  # bytes de texto base64 YA codificado


def _validar_limite_b64_seguro(bytes_b64_totales):
    if bytes_b64_totales > LIMITE_B64_SEGURO_POR_LLAMADA:
        raise ValueError(
            "Lo que quieres subir pesa demasiado para guardarse junto con el resto de la información "
            "de este registro (Firestore, la base de datos, tiene un límite duro de tamaño por "
            "registro). Sube un archivo más pequeño o comprime la imagen/PDF, o si son varios, "
            "súbelos en tandas más chicas."
        )


def archivo_a_b64(archivo_subido, max_bytes):
    """Convierte un archivo subido con st.file_uploader a (nombre, tipo, base64).
    Retorna (None, None, None) si no hay archivo. Lanza ValueError si excede
    max_bytes o el techo de seguridad de Firestore (ver LIMITE_B64_SEGURO_POR_LLAMADA)."""
    if archivo_subido is None:
        return None, None, None
    datos = archivo_subido.getvalue()
    if len(datos) > max_bytes:
        raise ValueError(
            f"El archivo pesa {len(datos) / 1000:.0f} KB; el máximo permitido es "
            f"{max_bytes / 1000:.0f} KB. Comprime la imagen o el PDF e intenta de nuevo."
        )
    b64 = base64.b64encode(datos).decode("ascii")
    _validar_limite_b64_seguro(len(b64))
    return archivo_subido.name, archivo_subido.type, b64


def archivos_a_b64_lista(archivos_subidos, max_bytes, max_archivos=3):
    """Convierte una lista de archivos subidos con
    st.file_uploader(accept_multiple_files=True) a una lista de
    {"nombre", "tipo", "b64"}. Retorna [] si no hay archivos. Lanza ValueError
    si se suben más de max_archivos, si alguno pesa más de max_bytes, o si el
    total ya codificado en base64 pasa el techo de seguridad de Firestore
    (ver LIMITE_B64_SEGURO_POR_LLAMADA)."""
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
                f"por archivo es {max_bytes / 1000:.0f} KB. Comprime la imagen o el PDF e intenta de nuevo."
            )
        b64 = base64.b64encode(datos).decode("ascii")
        total_b64 += len(b64)
        resultado.append({"nombre": archivo.name, "tipo": archivo.type, "b64": b64})
    _validar_limite_b64_seguro(total_b64)
    return resultado


def diseno_archivos_lista(d: dict) -> list:
    """Normaliza los archivos adjuntos de una solicitud de diseño: soporta
    tanto el formato nuevo (lista 'archivos') como el formato viejo (un solo
    archivo en 'archivo_nombre'/'archivo_tipo'/'archivo_b64'), para que las
    solicitudes creadas antes de este cambio se sigan viendo bien."""
    if d.get("archivos"):
        return d["archivos"]
    if d.get("archivo_b64"):
        return [{
            "nombre": d.get("archivo_nombre") or "archivo",
            "tipo": d.get("archivo_tipo") or "application/octet-stream",
            "b64": d["archivo_b64"],
        }]
    return []


# Versión pastel de la paleta de marca (CATEGORICAL), en el mismo orden, para
# las etiquetas de producto del resumen de Diseño Gráfico: (fondo, texto).
_CATEGORICAL_PASTEL = [
    ("#dce9fb", "#1c5cab"),
    ("#fbe3d5", "#b14d1f"),
    ("#d7f3e7", "#0f7a52"),
    ("#fdeecb", "#8a6100"),
    ("#fbe0ea", "#a83866"),
    ("#dcefdc", "#0a5c0a"),
    ("#e6e2f7", "#392a7a"),
    ("#fbdcdb", "#a32b2b"),
]


def _color_index(texto, cuantos):
    """Índice determinístico 0..cuantos-1 a partir de un texto (mismo texto
    siempre da el mismo índice, para que un vendedor o producto siempre
    tenga el mismo color)."""
    if not texto:
        return 0
    return int(hashlib.md5(texto.encode("utf-8")).hexdigest(), 16) % cuantos


def iniciales_nombre(nombre):
    """'Juan Pérez' -> 'JP'. Con un solo nombre, usa las primeras 2 letras."""
    partes = (nombre or "?").split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).upper()
    return (partes[0][:2] if partes and partes[0] else "?").upper()


def pastel_para_texto(texto):
    """Color pastel determinístico (fondo, texto) para una etiqueta tipo
    'tag' — mismo texto siempre da el mismo color, tomado de la paleta de marca."""
    return _CATEGORICAL_PASTEL[_color_index(texto, len(_CATEGORICAL_PASTEL))]


def avatar_color_para(texto):
    """Color sólido determinístico (de la paleta de marca) para el círculo
    de iniciales de un vendedor."""
    return CATEGORICAL[_color_index(texto, len(CATEGORICAL))]


def diseno_resumen_html(rows, estados_orden, column_emoji, columnas_con_semaforo, vendedores, hoy, manana):
    """Genera el HTML de un 'resumen de pendientes' estilo lista (como un
    tablero de Asana/Trello en modo lista), agrupado por columna del tablero
    de Diseño Gráfico, con avatar del vendedor, tag del producto y — donde
    aplica — el semáforo y una urgencia por fecha (Hoy / Mañana)."""
    hoy_s, manana_s = str(hoy), str(manana)
    secciones = []
    for estado in estados_orden:
        items = [r for r in rows if r.get("estado") == estado]
        filas_html = []
        for r in sorted(items, key=lambda x: x.get("fecha_necesaria") or "9999-99-99"):
            cliente = html.escape(r.get("cliente") or "Sin cliente")
            producto = html.escape(r.get("producto") or "—")
            fecha = r.get("fecha_necesaria")
            nombre_vend = db.nombre_vendedor(r.get("vendedor_id"), vendedores)
            av_bg = avatar_color_para(nombre_vend)
            iniciales = html.escape(iniciales_nombre(nombre_vend))
            p_bg, p_fg = pastel_para_texto(producto)

            pills = f'<span class="vd-pill" style="background:{p_bg};color:{p_fg};">{producto}</span>'

            if estado in columnas_con_semaforo:
                if r.get("detenido_emergencia"):
                    pills += '<span class="vd-pill" style="background:#fde8e8;color:#c62828;">🔴 Emergencia</span>'
                else:
                    pills += '<span class="vd-pill" style="background:#e4f7e4;color:#0ca30c;">🟢 En proceso</span>'

            if fecha and estado != "Entregado":
                if fecha == hoy_s:
                    pills += '<span class="vd-pill" style="background:#fde8e8;color:#c62828;">⏰ Hoy</span>'
                elif fecha == manana_s:
                    pills += '<span class="vd-pill" style="background:#fdeecb;color:#8a6100;">⏰ Mañana</span>'
                else:
                    pills += f'<span class="vd-pill" style="background:#eceae3;color:#52514e;">📅 {html.escape(fecha)}</span>'

            filas_html.append(
                '<div class="vd-resumen-row">'
                f'<span class="vd-avatar" style="background:{av_bg};" title="{html.escape(nombre_vend)}">{iniciales}</span>'
                f'<span class="vd-resumen-cliente">{cliente}</span>'
                f'<span class="vd-resumen-spacer">{pills}</span>'
                '</div>'
            )

        cuerpo = "".join(filas_html) or '<div class="vd-resumen-empty">Sin solicitudes en esta columna.</div>'
        secciones.append(
            '<div class="vd-resumen-section">'
            '<div class="vd-resumen-section-header">'
            f'<span>{column_emoji.get(estado, "")} {html.escape(estado)}</span>'
            f'<span class="vd-resumen-count">{len(items)}</span>'
            '</div>'
            f'{cuerpo}'
            '</div>'
        )

    estilo = (
        "<style>"
        ".vd-resumen-wrap{display:flex;flex-direction:column;gap:14px;margin-bottom:6px;}"
        ".vd-resumen-section{border:1px solid #e1e0d9;border-radius:10px;overflow:hidden;background:#fcfcfb;}"
        ".vd-resumen-section-header{display:flex;align-items:center;gap:8px;padding:10px 14px;"
        "background:#f5f4f0;border-bottom:1px solid #e1e0d9;font-weight:600;color:#0b0b0b;font-size:0.95rem;}"
        ".vd-resumen-count{margin-left:auto;background:#e1e0d9;color:#52514e;border-radius:999px;"
        "padding:1px 10px;font-size:0.78rem;font-weight:600;}"
        ".vd-resumen-row{display:flex;align-items:center;gap:10px;padding:9px 14px;"
        "border-bottom:1px solid #efeee9;font-size:0.87rem;}"
        ".vd-resumen-row:last-child{border-bottom:none;}"
        ".vd-resumen-cliente{font-weight:600;color:#0b0b0b;}"
        ".vd-avatar{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;"
        "justify-content:center;color:white;font-size:0.66rem;font-weight:700;flex-shrink:0;}"
        ".vd-pill{border-radius:999px;padding:2px 10px;font-size:0.72rem;font-weight:600;white-space:nowrap;}"
        ".vd-resumen-spacer{margin-left:auto;display:flex;gap:6px;align-items:center;"
        "flex-wrap:wrap;justify-content:flex-end;}"
        ".vd-resumen-empty{padding:12px 14px;color:#898781;font-size:0.85rem;font-style:italic;}"
        "</style>"
    )
    return estilo + '<div class="vd-resumen-wrap">' + "".join(secciones) + "</div>"


def mant_tiendas_resumen_html(rows, estados_orden, column_emoji, columnas_con_semaforo):
    """Genera el HTML de un 'resumen de pendientes' estilo lista para el
    tablero de Mantenimiento de Tiendas — mismo concepto y mismo estilo
    visual que diseno_resumen_html(), pero con las columnas/campos propios de
    este tablero (tienda, quién solicita) en vez de vendedor/producto/fecha."""
    secciones = []
    for estado in estados_orden:
        items = [r for r in rows if r.get("estado") == estado]
        filas_html = []
        for r in sorted(items, key=lambda x: x.get("creado_en") or "", reverse=True):
            quien = html.escape(r.get("quien_solicita") or "Sin especificar")
            tienda = html.escape(r.get("tienda") or "—")
            av_bg = avatar_color_para(quien)
            iniciales = html.escape(iniciales_nombre(quien))
            t_bg, t_fg = pastel_para_texto(tienda)

            pills = f'<span class="vd-pill" style="background:{t_bg};color:{t_fg};">{tienda}</span>'

            if estado in columnas_con_semaforo:
                if r.get("detenido_emergencia"):
                    pills += '<span class="vd-pill" style="background:#fde8e8;color:#c62828;">🔴 Emergencia</span>'
                else:
                    pills += '<span class="vd-pill" style="background:#e4f7e4;color:#0ca30c;">🟢 En proceso</span>'

            filas_html.append(
                '<div class="vd-resumen-row">'
                f'<span class="vd-avatar" style="background:{av_bg};" title="{quien}">{iniciales}</span>'
                f'<span class="vd-resumen-cliente">{quien}</span>'
                f'<span class="vd-resumen-spacer">{pills}</span>'
                '</div>'
            )

        cuerpo = "".join(filas_html) or '<div class="vd-resumen-empty">Sin solicitudes en esta columna.</div>'
        secciones.append(
            '<div class="vd-resumen-section">'
            '<div class="vd-resumen-section-header">'
            f'<span>{column_emoji.get(estado, "")} {html.escape(estado)}</span>'
            f'<span class="vd-resumen-count">{len(items)}</span>'
            '</div>'
            f'{cuerpo}'
            '</div>'
        )

    estilo = (
        "<style>"
        ".vd-resumen-wrap{display:flex;flex-direction:column;gap:14px;margin-bottom:6px;}"
        ".vd-resumen-section{border:1px solid #e1e0d9;border-radius:10px;overflow:hidden;background:#fcfcfb;}"
        ".vd-resumen-section-header{display:flex;align-items:center;gap:8px;padding:10px 14px;"
        "background:#f5f4f0;border-bottom:1px solid #e1e0d9;font-weight:600;color:#0b0b0b;font-size:0.95rem;}"
        ".vd-resumen-count{margin-left:auto;background:#e1e0d9;color:#52514e;border-radius:999px;"
        "padding:1px 10px;font-size:0.78rem;font-weight:600;}"
        ".vd-resumen-row{display:flex;align-items:center;gap:10px;padding:9px 14px;"
        "border-bottom:1px solid #efeee9;font-size:0.87rem;}"
        ".vd-resumen-row:last-child{border-bottom:none;}"
        ".vd-resumen-cliente{font-weight:600;color:#0b0b0b;}"
        ".vd-avatar{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;"
        "justify-content:center;color:white;font-size:0.66rem;font-weight:700;flex-shrink:0;}"
        ".vd-pill{border-radius:999px;padding:2px 10px;font-size:0.72rem;font-weight:600;white-space:nowrap;}"
        ".vd-resumen-spacer{margin-left:auto;display:flex;gap:6px;align-items:center;"
        "flex-wrap:wrap;justify-content:flex-end;}"
        ".vd-resumen-empty{padding:12px 14px;color:#898781;font-size:0.85rem;font-style:italic;}"
        "</style>"
    )
    return estilo + '<div class="vd-resumen-wrap">' + "".join(secciones) + "</div>"


def _pdf_safe(texto):
    """Los PDFs con fuentes estándar (Helvetica) solo soportan Latin-1. Si el
    vendedor pegó texto con símbolos raros (emojis, comillas curvas, etc.),
    los reemplaza por '?' en vez de hacer fallar la generación del PDF."""
    return str(texto).encode("latin-1", "replace").decode("latin-1")


def diseno_pdf_bytes(d: dict, vendedor_nombre: str) -> bytes:
    """Genera un PDF tipo 'orden de compra' con toda la información inicial
    de una solicitud de diseño gráfico."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _pdf_safe(EMPRESA_NOMBRE), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _pdf_safe("Solicitud de Diseño Gráfico"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _pdf_safe(f"Folio: {d.get('id', '')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    campos = [
        ("Vendedor", vendedor_nombre or "-"),
        ("Cliente", d.get("cliente") or "-"),
        ("Producto", d.get("producto") or "-"),
        ("Material", d.get("material") or "-"),
        ("Acabado", d.get("acabado") or "-"),
        ("Medida", d.get("medida") or "-"),
        ("Fecha en que se necesita", d.get("fecha_necesaria") or "-"),
        ("Fecha de solicitud", (d.get("creado_en") or "-")[:10]),
        ("Estado actual", d.get("estado") or "-"),
        ("Cambios necesarios", d.get("cambios_necesarios") or "-"),
        (
            "Archivos adjuntos",
            ", ".join(a["nombre"] for a in diseno_archivos_lista(d)) or "Sin archivos adjuntos",
        ),
    ]
    for etiqueta, valor in campos:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _pdf_safe(f"{etiqueta}:"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 7, _pdf_safe(valor))
        pdf.ln(1)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, _pdf_safe("Documento generado automáticamente por la Plataforma Comercial - Visión Digital."))

    return bytes(pdf.output())


def pedido_pdf_bytes(p: dict) -> bytes:
    """Genera el PDF de 'ENVÍO No. ____' de un pedido de Logística, con el
    mismo diseño que la libreta física de envíos que se usaba en papel
    (encabezado con logo y número de envío, datos de FECHA/ATENCIÓN A/
    CLIENTE/DIRECCIÓN, tabla de CANTIDAD/DESCRIPCIÓN y las líneas de firma
    ENVÍA/RECIBE al final)."""
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)

    # -- Encabezado: logo a la izquierda, caja "ENVÍO No." a la derecha -----
    try:
        pdf.image(LOGO_PATH, x=10, y=10, w=42)
    except Exception:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 12)
        pdf.cell(60, 8, _pdf_safe(EMPRESA_NOMBRE))

    caja_x, caja_w = 138, 64
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(caja_x, 12)
    pdf.cell(caja_w, 8, _pdf_safe("ENVÍO No."), border=0, align="C", fill=True)

    numero_envio = p.get("numero_envio")
    texto_numero = f"No. {numero_envio:04d}" if isinstance(numero_envio, int) else "No. ____"
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(caja_x, 20)
    pdf.cell(caja_w, 10, _pdf_safe(texto_numero), border=1, align="C")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(caja_x, 32)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA1), align="C")
    pdf.set_xy(caja_x, 37)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA2), align="C")
    pdf.set_text_color(0, 0, 0)

    # -- Datos del envío: FECHA / ATENCIÓN A / CLIENTE / DIRECCIÓN / N° ORDEN --
    fecha_txt = p.get("fecha") or ""
    if len(fecha_txt) == 10 and fecha_txt[4] == "-":
        fecha_txt = f"{fecha_txt[8:10]}/{fecha_txt[5:7]}/{fecha_txt[0:4]}"

    campos = [
        ("FECHA:", fecha_txt or "—"),
        ("ATENCIÓN A:", p.get("atencion_a") or "—"),
        ("CLIENTE:", p.get("cliente") or "—"),
        ("DIRECCIÓN:", p.get("direccion") or "—"),
        ("N° ORDEN:", p.get("numero_orden") or "—"),
    ]
    box_y0, fila_h, box_w = 52, 9, 190
    pdf.set_draw_color(150, 150, 150)
    pdf.rect(10, box_y0, box_w, fila_h * len(campos))
    for i, (etiqueta, valor) in enumerate(campos):
        fila_y = box_y0 + i * fila_h
        if i > 0:
            pdf.line(10, fila_y, 10 + box_w, fila_y)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(13, fila_y + 2.3)
        pdf.cell(35, 5, _pdf_safe(etiqueta))
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(45, fila_y + 2.3)
        pdf.cell(box_w - 38, 5, _pdf_safe(valor))

    # -- Tabla CANTIDAD / DESCRIPCIÓN ----------------------------------------
    productos = [
        it for it in (p.get("productos") or [])
        if (it.get("cantidad") or "").strip() or (it.get("descripcion") or "").strip()
    ]
    if not productos and p.get("producto"):
        productos = [{"cantidad": "", "descripcion": p["producto"]}]

    tabla_y0 = box_y0 + fila_h * len(campos) + 6
    col_cant_w, col_desc_w = 35, box_w - 35
    fila_tabla_h = 8
    num_filas = max(10, len(productos) + 1)

    pdf.set_xy(10, tabla_y0)
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(col_cant_w, fila_tabla_h, _pdf_safe("CANTIDAD"), border=0, align="C", fill=True)
    pdf.cell(col_desc_w, fila_tabla_h, _pdf_safe("DESCRIPCIÓN"), border=0, align="C", fill=True)
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_draw_color(150, 150, 150)
    line_h = 5
    fila_y = tabla_y0 + fila_tabla_h
    for i in range(num_filas):
        cant = productos[i]["cantidad"] if i < len(productos) else ""
        desc = productos[i]["descripcion"] if i < len(productos) else ""
        desc_txt = _pdf_safe(f" {desc}") if desc else ""
        if desc_txt:
            # Calcula cuántas líneas necesita la descripción para no salirse
            # de su columna (pedidos con varios productos largos) y usa esa
            # altura para ambas celdas de la fila, para que el borde quede
            # parejo entre "Cantidad" y "Descripción".
            lineas = pdf.multi_cell(col_desc_w, line_h, desc_txt, dry_run=True, output="LINES")
            alto_fila = max(fila_tabla_h, len(lineas) * line_h + 3)
        else:
            alto_fila = fila_tabla_h
        pdf.set_xy(10, fila_y)
        pdf.cell(col_cant_w, alto_fila, _pdf_safe(cant), border=1, align="C")
        pdf.set_xy(10 + col_cant_w, fila_y)
        pdf.multi_cell(col_desc_w, line_h, desc_txt, border=1)
        fila_y += alto_fila

    # -- Firmas: ENVÍA / RECIBE ----------------------------------------------
    # El hueco antes de las líneas se agranda un poco (de 18 a 26) respecto
    # al resto del PDF para dejarle espacio arriba a la firma escaneada de
    # "ENVÍA", que se centra sobre esa misma línea.
    firmas_y = fila_y + 26
    try:
        firma_w = 30
        pdf.image(FIRMA_ENVIO_PATH, x=15 + (80 - firma_w) / 2, y=firmas_y - 20, w=firma_w)
    except Exception:
        pass
    pdf.set_draw_color(0, 0, 0)
    pdf.line(15, firmas_y, 95, firmas_y)
    pdf.line(115, firmas_y, 195, firmas_y)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(15, firmas_y + 2)
    pdf.cell(80, 5, _pdf_safe("ENVÍA"), align="C")
    pdf.set_xy(115, firmas_y + 2)
    pdf.cell(80, 5, _pdf_safe("RECIBE"), align="C")

    # Debajo de "ENVÍA" va el nombre y puesto de quien firma ahí siempre
    # (Carlos, Jefe de Logística) en vez del texto genérico "Firma y Nombre".
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(15, firmas_y + 7)
    pdf.cell(80, 5, _pdf_safe(FIRMA_ENVIO_NOMBRE), align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(15, firmas_y + 12)
    pdf.cell(80, 5, _pdf_safe(FIRMA_ENVIO_PUESTO), align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(115, firmas_y + 7)
    pdf.cell(80, 5, _pdf_safe("Firma, Nombre y Sello."), align="C")

    return bytes(pdf.output())


def cotizador_digital_pdf_bytes(cot: dict, prospecto: dict | None, vendedor_nombre: str) -> bytes:
    """PDF limpio, con marca Visión Digital, de una cotización generada desde
    el Cotizador Digital — pensado para descargarse y enviarse directo al
    cliente (no replica el layout del Excel B01 original, solo sus datos)."""
    resultado = cot.get("resultado") or {}
    detalle = cot.get("detalle") or {}
    numero_txt = f"CD-{cot.get('numero', 0):04d}"

    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    try:
        pdf.image(LOGO_PATH, x=10, y=10, w=42)
    except Exception:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 12)
        pdf.cell(60, 8, _pdf_safe(EMPRESA_NOMBRE))

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(120, 12)
    pdf.cell(80, 8, _pdf_safe("COTIZACIÓN"), align="R")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(120, 21)
    pdf.cell(80, 6, _pdf_safe(numero_txt), align="R")
    fecha_txt = (cot.get("creado_en") or "")[:10] or str(date.today())
    pdf.set_xy(120, 27)
    pdf.cell(80, 6, _pdf_safe(f"Fecha: {fecha_txt}"), align="R")

    pdf.set_y(38)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _pdf_safe("Cliente"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _pdf_safe(prospecto["nombre_cliente"] if prospecto else "—"), new_x="LMARGIN", new_y="NEXT")
    if prospecto and prospecto.get("direccion"):
        pdf.cell(0, 6, _pdf_safe(prospecto["direccion"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _pdf_safe(f"Vendedor: {vendedor_nombre or '—'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _pdf_safe(cot.get("nombre_producto") or "Producto"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    campos = [
        ("Material", detalle.get("material")),
        ("Impresión", detalle.get("impresion")),
        ("Tamaño", detalle.get("tamano")),
        ("Cantidad", detalle.get("cantidad")),
        ("Procesos incluidos", detalle.get("procesos")),
    ]
    for etiqueta, valor in campos:
        if valor in (None, "", "—"):
            continue
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(10)
        pdf.cell(45, 6, _pdf_safe(f"{etiqueta}:"))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _pdf_safe(str(valor)), new_x="LMARGIN", new_y="NEXT")

    if cot.get("notas"):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _pdf_safe("Notas:"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _pdf_safe(cot["notas"]))

    pdf.ln(6)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    precio_unitario = resultado.get("precio_unitario") or 0.0
    total = resultado.get("total") or 0.0
    cantidad = detalle.get("cantidad") or 1

    box_y = pdf.get_y()
    pdf.set_fill_color(245, 245, 245)
    pdf.rect(120, box_y, 80, 26, style="F")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(124, box_y + 3)
    pdf.cell(72, 6, _pdf_safe(f"Precio unitario: {money(precio_unitario)}"))
    pdf.set_xy(124, box_y + 10)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(72, 8, _pdf_safe(f"Total: {money(total)}"))
    pdf.set_xy(124, box_y + 19)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(72, 5, _pdf_safe(f"Cantidad: {cantidad}"))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(32)

    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(
        0, 5,
        _pdf_safe(
            "Cotización válida por 15 días a partir de la fecha de emisión. Precios sujetos a cambio sin previo "
            "aviso. Documento generado automáticamente por la Plataforma Comercial - Visión Digital."
        ),
    )

    return bytes(pdf.output())


def mant_tienda_pdf_bytes(r: dict) -> bytes:
    """Genera el PDF de 'ORDEN DE TRABAJO No. ____' de una solicitud de
    Mantenimiento de Tiendas — mismo diseño que el PDF de 'ENVÍO No.' de
    Logística (encabezado con logo y número corrido, caja de datos, y las
    líneas de firma al final), adaptado a los campos propios de este
    tablero (tienda, quién solicita, descripción del problema) en vez de la
    tabla de productos de un envío."""
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)

    # -- Encabezado: logo a la izquierda, caja "ORDEN DE TRABAJO No." a la derecha --
    try:
        pdf.image(LOGO_PATH, x=10, y=10, w=42)
    except Exception:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 12)
        pdf.cell(60, 8, _pdf_safe(EMPRESA_NOMBRE))

    caja_x, caja_w = 128, 74
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(caja_x, 12)
    pdf.cell(caja_w, 8, _pdf_safe("ORDEN DE TRABAJO No."), border=0, align="C", fill=True)

    numero_solicitud = r.get("numero_solicitud")
    texto_numero = f"No. {numero_solicitud:04d}" if isinstance(numero_solicitud, int) else "No. ____"
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(caja_x, 20)
    pdf.cell(caja_w, 10, _pdf_safe(texto_numero), border=1, align="C")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(caja_x, 32)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA1), align="C")
    pdf.set_xy(caja_x, 37)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA2), align="C")
    pdf.set_text_color(0, 0, 0)

    # -- Datos de la solicitud: FECHA / TIENDA / SOLICITA / ESTADO -----------
    fecha_txt = (r.get("creado_en") or "")[:10]
    if len(fecha_txt) == 10 and fecha_txt[4] == "-":
        fecha_txt = f"{fecha_txt[8:10]}/{fecha_txt[5:7]}/{fecha_txt[0:4]}"

    campos = [
        ("FECHA:", fecha_txt or "—"),
        ("TIENDA:", r.get("tienda") or "—"),
        ("SOLICITA:", r.get("quien_solicita") or "—"),
        ("ESTADO:", r.get("estado") or "—"),
    ]
    box_y0, fila_h, box_w = 52, 9, 190
    pdf.set_draw_color(150, 150, 150)
    pdf.rect(10, box_y0, box_w, fila_h * len(campos))
    for i, (etiqueta, valor) in enumerate(campos):
        fila_y = box_y0 + i * fila_h
        if i > 0:
            pdf.line(10, fila_y, 10 + box_w, fila_y)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(13, fila_y + 2.3)
        pdf.cell(35, 5, _pdf_safe(etiqueta))
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(45, fila_y + 2.3)
        pdf.cell(box_w - 38, 5, _pdf_safe(valor))

    # -- Descripción del problema --------------------------------------------
    desc_y0 = box_y0 + fila_h * len(campos) + 6
    pdf.set_xy(10, desc_y0)
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(box_w, 8, _pdf_safe("DESCRIPCIÓN DEL PROBLEMA"), border=0, align="C", fill=True)
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_draw_color(150, 150, 150)
    pdf.set_xy(10, desc_y0 + 8)
    texto_desc = _pdf_safe(r.get("descripcion") or "Sin descripción.")
    lineas = pdf.multi_cell(box_w, 6, texto_desc, dry_run=True, output="LINES")
    alto_desc = max(24, len(lineas) * 6 + 6)
    pdf.multi_cell(box_w, 6, texto_desc, border=1)
    pdf.rect(10, desc_y0 + 8, box_w, alto_desc)

    # -- Fotos de la solicitud inicial ---------------------------------------
    fotos_y0 = desc_y0 + 8 + alto_desc + 6
    fotos = r.get("fotos") or []
    pdf.set_xy(10, fotos_y0)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90, 90, 90)
    if not fotos:
        pdf.cell(box_w, 5, _pdf_safe("Sin fotos adjuntas."))
        pdf.set_text_color(0, 0, 0)
        firmas_y = fotos_y0 + 20
    else:
        pdf.cell(box_w, 5, _pdf_safe(f"📷 Fotos de la solicitud ({len(fotos)}):"))
        pdf.set_text_color(0, 0, 0)
        img_w, img_h, gap = 58, 44, 4
        img_y = fotos_y0 + 7
        x_cursor = 10
        col_i = 0
        for foto in fotos:
            try:
                img_bytes = base64.b64decode(foto.get("b64") or "")
                img_stream = io.BytesIO(img_bytes)
                # Si la foto no cabe antes del margen inferior, se pasa a una
                # página nueva en vez de encimarse con las líneas de firma.
                if img_y + img_h > 235:
                    pdf.add_page()
                    img_y = 15
                    x_cursor = 10
                    col_i = 0
                pdf.image(img_stream, x=x_cursor, y=img_y, w=img_w, h=img_h)
            except Exception:
                # Foto dañada o formato no soportado por fpdf2 — se omite en
                # vez de hacer fallar la generación de todo el PDF.
                continue
            col_i += 1
            if col_i >= 3:
                col_i = 0
                x_cursor = 10
                img_y += img_h + gap
            else:
                x_cursor += img_w + gap
        if col_i != 0:
            img_y += img_h + gap
        firmas_y = img_y + 14

    # -- Firmas: SOLICITA / ATIENDE MANTENIMIENTO ----------------------------
    pdf.set_draw_color(0, 0, 0)
    pdf.line(15, firmas_y, 95, firmas_y)
    pdf.line(115, firmas_y, 195, firmas_y)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(15, firmas_y + 2)
    pdf.cell(80, 5, _pdf_safe("SOLICITA"), align="C")
    pdf.set_xy(115, firmas_y + 2)
    pdf.cell(80, 5, _pdf_safe("ATIENDE MANTENIMIENTO"), align="C")
    pdf.set_xy(15, firmas_y + 7)
    pdf.cell(80, 5, _pdf_safe("Firma y Nombre"), align="C")
    pdf.set_xy(115, firmas_y + 7)
    pdf.cell(80, 5, _pdf_safe("Firma y Nombre"), align="C")

    return bytes(pdf.output())


def minuta_tienda_pdf_bytes(m: dict, metas: list | None = None) -> bytes:
    """Genera el PDF profesional (con logo de Visión Digital) de una Minuta
    de Tienda — ver 28_Minutas_Tiendas.py. Trae las 3 secciones que pidió
    Steven: (1) el checklist de temas tratados en la reunión, (2) los
    pendientes solicitados y (3) metas vs. ventas por asesor de ventas del
    mes de la reunión. 'metas' es la lista que retorna
    database.list_metas_tienda(tienda=m['tienda'], mes=...) ya filtrada al
    mes correcto — se recibe aparte porque 'm' (la minuta) no guarda esos
    datos. Se genera siempre al vuelo a partir de lo que ya está guardado
    en Firestore — no se guarda el PDF en ningún lado, así que tanto el
    botón de 'Ver PDF' dentro de la plataforma como el correo automático
    al crear la minuta simplemente lo vuelven a generar cuando se
    necesita (mismo patrón que mant_tienda_pdf_bytes)."""
    metas = metas or []
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    box_w = 190

    # -- Encabezado: logo a la izquierda, caja "MINUTA DE TIENDA No." a la derecha --
    try:
        pdf.image(LOGO_PATH, x=10, y=10, w=42)
    except Exception:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 12)
        pdf.cell(60, 8, _pdf_safe(EMPRESA_NOMBRE))

    caja_x, caja_w = 122, 80
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(caja_x, 12)
    pdf.cell(caja_w, 8, _pdf_safe("MINUTA DE TIENDA No."), border=0, align="C", fill=True)

    numero = m.get("numero")
    texto_numero = f"MIN-{numero:04d}" if isinstance(numero, int) else "MIN-____"
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(caja_x, 20)
    pdf.cell(caja_w, 10, _pdf_safe(texto_numero), border=1, align="C")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(caja_x, 32)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA1), align="C")
    pdf.set_xy(caja_x, 37)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA2), align="C")
    pdf.set_text_color(0, 0, 0)

    # -- Datos de la reunión: FECHA / TIENDA / ELABORADA POR ------------------
    fecha_txt = m.get("fecha_reunion") or ""
    if len(fecha_txt) == 10 and fecha_txt[4] == "-":
        fecha_txt = f"{fecha_txt[8:10]}/{fecha_txt[5:7]}/{fecha_txt[0:4]}"

    campos = [
        ("FECHA DE REUNIÓN:", fecha_txt or "—"),
        ("TIENDA:", m.get("tienda") or "—"),
        ("ELABORADA POR:", m.get("creado_por_nombre") or "—"),
    ]
    box_y0, fila_h = 52, 9
    pdf.set_draw_color(150, 150, 150)
    pdf.rect(10, box_y0, box_w, fila_h * len(campos))
    for i, (etiqueta, valor) in enumerate(campos):
        fila_y = box_y0 + i * fila_h
        if i > 0:
            pdf.line(10, fila_y, 10 + box_w, fila_y)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(13, fila_y + 2.3)
        pdf.cell(45, 5, _pdf_safe(etiqueta))
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(58, fila_y + 2.3)
        pdf.cell(box_w - 48, 5, _pdf_safe(valor))

    y = box_y0 + fila_h * len(campos) + 8

    def _titulo_seccion(texto, y0):
        pdf.set_xy(10, y0)
        pdf.set_fill_color(20, 20, 20)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(box_w, 7, _pdf_safe(texto), border=0, align="L", fill=True)
        pdf.set_text_color(0, 0, 0)
        return y0 + 7

    def _salto_pagina_si_necesario(y_actual, espacio_necesario=20):
        if y_actual + espacio_necesario > 270:
            pdf.add_page()
            return 15
        return y_actual

    # -- 1) Checklist de temas tratados --------------------------------------
    y = _salto_pagina_si_necesario(y, 20)
    y = _titulo_seccion(" 1. CHECKLIST DE TEMAS TRATADOS", y)
    checklist = m.get("checklist") or []
    col_marca_w = 22
    pdf.set_draw_color(150, 150, 150)
    if not checklist:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_xy(10, y + 2)
        pdf.cell(box_w, 6, _pdf_safe("Sin temas registrados."))
        y += 10
    else:
        for item in checklist:
            texto_tema = item.get("tema") or ""
            if item.get("extra"):
                texto_tema += "  (agregado, no estaba en la lista)"
            texto_tema = _pdf_safe(texto_tema)
            y = _salto_pagina_si_necesario(y, 8)
            lineas = pdf.multi_cell(box_w - col_marca_w, 5.5, texto_tema, dry_run=True, output="LINES")
            alto_fila = max(7, len(lineas) * 5.5 + 2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_xy(10, y)
            marca = "SI" if item.get("tratado") else "NO"
            pdf.cell(col_marca_w, alto_fila, _pdf_safe(marca), border=1, align="C")
            pdf.set_font("Helvetica", "", 10)
            pdf.set_xy(10 + col_marca_w, y)
            pdf.multi_cell(box_w - col_marca_w, 5.5, texto_tema, border=1)
            y += alto_fila
    y += 6

    # -- 2) Pendientes solicitados --------------------------------------------
    y = _salto_pagina_si_necesario(y, 20)
    y = _titulo_seccion(" 2. PENDIENTES SOLICITADOS", y)
    pendientes = m.get("pendientes") or []
    if not pendientes:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_xy(10, y + 2)
        pdf.cell(box_w, 6, _pdf_safe("Sin pendientes registrados."))
        y += 10
    else:
        col_desc_w, col_resp_w, col_edo_w = 92, 58, 40
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(235, 235, 235)
        pdf.set_xy(10, y)
        pdf.cell(col_desc_w, 6, _pdf_safe("Descripción"), border=1, align="C", fill=True)
        pdf.cell(col_resp_w, 6, _pdf_safe("Responsable / Límite"), border=1, align="C", fill=True)
        pdf.cell(col_edo_w, 6, _pdf_safe("Estado"), border=1, align="C", fill=True)
        y += 6
        pdf.set_font("Helvetica", "", 9)
        for p in pendientes:
            desc_txt = _pdf_safe(p.get("descripcion") or "—")
            responsable_txt = p.get("responsable") or "—"
            limite = p.get("fecha_limite")
            resp_txt = _pdf_safe(f"{responsable_txt} / {limite}" if limite else responsable_txt)
            estado_txt = _pdf_safe(p.get("estado") or "Pendiente")
            y = _salto_pagina_si_necesario(y, 8)
            lineas_desc = pdf.multi_cell(col_desc_w, 5, desc_txt, dry_run=True, output="LINES")
            alto_fila = max(6, len(lineas_desc) * 5 + 3)
            pdf.set_xy(10, y)
            pdf.multi_cell(col_desc_w, 5, desc_txt, border=1)
            pdf.set_xy(10 + col_desc_w, y)
            pdf.cell(col_resp_w, alto_fila, resp_txt, border=1)
            pdf.set_xy(10 + col_desc_w + col_resp_w, y)
            pdf.cell(col_edo_w, alto_fila, estado_txt, border=1, align="C")
            y += alto_fila
    y += 6

    # -- 3) Metas vs. ventas por asesor de ventas -----------------------------
    y = _salto_pagina_si_necesario(y, 20)
    y = _titulo_seccion(" 3. METAS VS. VENTAS POR ASESOR DE VENTAS", y)
    if not metas:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_xy(10, y + 2)
        pdf.cell(
            box_w, 6,
            _pdf_safe("Sin metas/ventas registradas para el mes de esta reunión."),
        )
        y += 10
    else:
        col_ase_w, col_meta_w, col_venta_w, col_pct_w = 68, 40, 40, 42
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(235, 235, 235)
        pdf.set_xy(10, y)
        pdf.cell(col_ase_w, 6, _pdf_safe("Asesor de ventas"), border=1, align="C", fill=True)
        pdf.cell(col_meta_w, 6, _pdf_safe("Meta (Q)"), border=1, align="C", fill=True)
        pdf.cell(col_venta_w, 6, _pdf_safe("Venta actual (Q)"), border=1, align="C", fill=True)
        pdf.cell(col_pct_w, 6, _pdf_safe("% cumplimiento"), border=1, align="C", fill=True)
        y += 6
        pdf.set_font("Helvetica", "", 9)
        total_meta = total_venta = 0.0
        for r in sorted(metas, key=lambda r: r.get("asesor_nombre") or ""):
            meta_val = float(r.get("meta") or 0.0)
            venta_val = float(r.get("venta_actual") or 0.0)
            total_meta += meta_val
            total_venta += venta_val
            pct_txt = f"{(venta_val / meta_val * 100):.0f}%" if meta_val else "—"
            y = _salto_pagina_si_necesario(y, 8)
            pdf.set_xy(10, y)
            pdf.cell(col_ase_w, 6, _pdf_safe(r.get("asesor_nombre") or "—"), border=1)
            pdf.cell(col_meta_w, 6, _pdf_safe(f"Q {meta_val:,.2f}"), border=1, align="R")
            pdf.cell(col_venta_w, 6, _pdf_safe(f"Q {venta_val:,.2f}"), border=1, align="R")
            pdf.cell(col_pct_w, 6, _pdf_safe(pct_txt), border=1, align="C")
            y += 6
        pct_total_txt = f"{(total_venta / total_meta * 100):.0f}%" if total_meta else "—"
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(10, y)
        pdf.cell(col_ase_w, 6, _pdf_safe("TOTAL"), border=1)
        pdf.cell(col_meta_w, 6, _pdf_safe(f"Q {total_meta:,.2f}"), border=1, align="R")
        pdf.cell(col_venta_w, 6, _pdf_safe(f"Q {total_venta:,.2f}"), border=1, align="R")
        pdf.cell(col_pct_w, 6, _pdf_safe(pct_total_txt), border=1, align="C")
        y += 6
    y += 8

    # -- Notas generales -------------------------------------------------------
    if m.get("notas_generales"):
        y = _salto_pagina_si_necesario(y, 16)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(10, y)
        pdf.cell(box_w, 6, _pdf_safe("Notas generales:"))
        y += 6
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(10, y)
        pdf.multi_cell(box_w, 5.5, _pdf_safe(m["notas_generales"]))
        y = pdf.get_y() + 4

    pdf.set_y(max(y, pdf.get_y()) + 4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, _pdf_safe("Documento generado automáticamente por la Plataforma Comercial - Visión Digital."))

    return bytes(pdf.output())


def orden_produccion_pdf_bytes(p: dict, linea: str) -> bytes:
    """Genera el PDF de 'ORDEN DE PRODUCCIÓN No. ____' de una orden de
    Colorado o Galaxy — mismo diseño que el PDF de 'ENVÍO No.' de Logística
    y el de 'ORDEN DE TRABAJO No.' de Mantenimiento de Tiendas (encabezado
    con logo y número corrido, cajas de datos, y las líneas de firma al
    final), adaptado a los campos propios de una orden de producción
    (cliente, pieza, dimensiones, material, color, acabados, precio,
    cantidad, notas). 'linea' es "Colorado" o "Galaxy", para identificar de
    cuál tablero viene la orden."""
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)

    # -- Encabezado: logo a la izquierda, caja "ORDEN DE PRODUCCIÓN No." a la derecha --
    try:
        pdf.image(LOGO_PATH, x=10, y=10, w=42)
    except Exception:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 12)
        pdf.cell(60, 8, _pdf_safe(EMPRESA_NOMBRE))

    caja_x, caja_w = 108, 92
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(caja_x, 12)
    pdf.cell(caja_w, 8, _pdf_safe("ORDEN DE PRODUCCIÓN No."), border=0, align="C", fill=True)

    numero_orden = p.get("numero_orden")
    texto_numero = f"No. {numero_orden:04d}" if isinstance(numero_orden, int) else "No. ____"
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(caja_x, 20)
    pdf.cell(caja_w, 10, _pdf_safe(texto_numero), border=1, align="C")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(caja_x, 32)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA1), align="C")
    pdf.set_xy(caja_x, 37)
    pdf.cell(caja_w, 5, _pdf_safe(EMPRESA_DIRECCION_LINEA2), align="C")
    pdf.set_text_color(0, 0, 0)

    def _fecha_legible(iso_txt):
        iso_txt = (iso_txt or "")[:10]
        if len(iso_txt) == 10 and iso_txt[4] == "-":
            return f"{iso_txt[8:10]}/{iso_txt[5:7]}/{iso_txt[0:4]}"
        return iso_txt

    total = None
    if p.get("precio_unidad") and p.get("cantidad_unidades"):
        total = float(p["precio_unidad"]) * float(p["cantidad_unidades"])

    dimensiones = None
    if p.get("dimension_ancho") or p.get("dimension_alto"):
        dimensiones = (
            f"{p.get('dimension_ancho') or '—'} x {p.get('dimension_alto') or '—'} "
            f"{p.get('dimension_unidad') or ''}"
        ).strip()

    box_w = 190

    def _caja(y0, titulo_caja, campos):
        fila_h = 8
        if titulo_caja:
            pdf.set_xy(10, y0)
            pdf.set_fill_color(20, 20, 20)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(box_w, 7, _pdf_safe(titulo_caja), border=0, align="C", fill=True)
            pdf.set_text_color(0, 0, 0)
            y0 += 7
        pdf.set_draw_color(150, 150, 150)
        pdf.rect(10, y0, box_w, fila_h * len(campos))
        for i, (etiqueta, valor) in enumerate(campos):
            fila_y = y0 + i * fila_h
            if i > 0:
                pdf.line(10, fila_y, 10 + box_w, fila_y)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_xy(13, fila_y + 2.3)
            pdf.cell(48, 5, _pdf_safe(etiqueta))
            pdf.set_font("Helvetica", "", 10)
            pdf.set_xy(61, fila_y + 2.3)
            pdf.cell(box_w - 54, 5, _pdf_safe(valor))
        return y0 + fila_h * len(campos)

    y = 52
    y = _caja(y, "DATOS DEL CLIENTE", [
        ("LÍNEA:", linea),
        ("FECHA:", _fecha_legible(p.get("creado_en")) or "—"),
        ("SOLICITA:", p.get("quien_solicita") or "—"),
        ("CLIENTE:", p.get("cliente_nombre") or "—"),
        ("TELÉFONO:", p.get("cliente_telefono") or "—"),
        ("CORREO:", p.get("cliente_correo") or "—"),
        ("NIT:", p.get("nit") or "—"),
        ("DIRECCIÓN DE ENTREGA:", p.get("direccion_entrega") or "—"),
    ])
    y += 6
    y = _caja(y, "DATOS DE LA PIEZA", [
        ("TIPO DE PIEZA:", p.get("tipo_pieza") or "—"),
        ("DIMENSIONES:", dimensiones or "—"),
        ("MATERIAL:", p.get("material") or "—"),
        ("TIPO DE COLOR:", p.get("tipo_color") or "—"),
        ("ACABADOS:", p.get("acabados") or "—"),
    ])
    y += 6
    y = _caja(y, "PRECIO Y ENTREGA", [
        ("PRECIO POR UNIDAD:", money(p["precio_unidad"]) if p.get("precio_unidad") else "—"),
        ("CANTIDAD:", str(p["cantidad_unidades"]) if p.get("cantidad_unidades") not in (None, "") else "—"),
        ("TOTAL:", money(total) if total is not None else "—"),
        ("FECHA DE ENTREGA:", _fecha_legible(p.get("fecha_entrega")) or "Sin definir"),
    ])
    y += 6

    # -- Notas adicionales ----------------------------------------------------
    pdf.set_xy(10, y)
    pdf.set_fill_color(20, 20, 20)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(box_w, 7, _pdf_safe("NOTAS ADICIONALES"), border=0, align="C", fill=True)
    pdf.set_text_color(0, 0, 0)
    y += 7
    pdf.set_font("Helvetica", "", 10)
    pdf.set_draw_color(150, 150, 150)
    pdf.set_xy(10, y)
    texto_notas = _pdf_safe(p.get("notas") or "Sin notas.")
    lineas = pdf.multi_cell(box_w, 6, texto_notas, dry_run=True, output="LINES")
    alto_notas = max(16, len(lineas) * 6 + 4)
    pdf.multi_cell(box_w, 6, texto_notas, border=1)
    pdf.rect(10, y, box_w, alto_notas)
    y += alto_notas + 6

    # -- Archivos adjuntos (solo el nombre — pueden ser PDF, Word, Excel,
    # PSD o AI, formatos que fpdf2 no puede dibujar como imagen) ------------
    archivos = p.get("archivos") or []
    if y > 250:
        pdf.add_page()
        y = 15
    pdf.set_xy(10, y)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90, 90, 90)
    if archivos:
        nombres = ", ".join(a.get("nombre") or "archivo" for a in archivos)
        pdf.multi_cell(box_w, 5, _pdf_safe(f"Archivos adjuntos ({len(archivos)}): {nombres}"))
    else:
        pdf.cell(box_w, 5, _pdf_safe("Sin archivos adjuntos."))
    pdf.set_text_color(0, 0, 0)
    y = pdf.get_y() + 14

    # -- Firmas: SOLICITA / PRODUCCIÓN ---------------------------------------
    if y > 255:
        pdf.add_page()
        y = 20
    pdf.set_draw_color(0, 0, 0)
    pdf.line(15, y, 95, y)
    pdf.line(115, y, 195, y)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(15, y + 2)
    pdf.cell(80, 5, _pdf_safe("SOLICITA"), align="C")
    pdf.set_xy(115, y + 2)
    pdf.cell(80, 5, _pdf_safe("PRODUCCIÓN"), align="C")
    pdf.set_xy(15, y + 7)
    pdf.cell(80, 5, _pdf_safe("Firma y Nombre"), align="C")
    pdf.set_xy(115, y + 7)
    pdf.cell(80, 5, _pdf_safe("Firma y Nombre"), align="C")

    return bytes(pdf.output())


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
    (hoja horizontal tipo certificado): logo de Visión Digital, nombre del
    empleado, tienda, módulo completado, fecha, y la firma de Steven Gabriel
    (Gerente Comercial) al calce. 'fecha' puede ser un date o un string
    'YYYY-MM-DD'."""
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
    pdf.set_draw_color(255, 12, 130)  # BRAND_PINK
    pdf.set_line_width(2.2)
    pdf.rect(8, 8, ancho - 16, alto - 16)
    pdf.set_draw_color(20, 20, 20)
    pdf.set_line_width(0.4)
    pdf.rect(12.5, 12.5, ancho - 25, alto - 25)
    pdf.set_line_width(0.2)

    # -- Logo, centrado arriba (el logo real es ancho:alto ≈ 1 : 0.51) ----------
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
    pdf.cell(ancho, 8, _pdf_safe("Programa de Capacitación - Visión Digital"), align="C")

    # -- "Se otorga a" + nombre del empleado -------------------------------------
    pdf.set_text_color(90, 90, 90)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(0, y_cursor + 30)
    pdf.cell(ancho, 8, _pdf_safe("Se otorga el presente reconocimiento a"), align="C")

    pdf.set_text_color(255, 12, 130)  # BRAND_PINK
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
    pdf.cell(ancho, 7, _pdf_safe(f"Tienda: {tienda or '—'}"), align="C")

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

    # Derecha: firma escaneada + nombre y puesto — la firma se centra sobre
    # el mismo bloque (161 a 241) que la línea, el nombre y el puesto, para
    # que quede justo encima de "Steven Gabriel" y no desplazada.
    try:
        firma_w = 46
        pdf.image(FIRMA_STEVEN_PATH, x=161 + (80 - firma_w) / 2, y=firmas_y - 18, w=firma_w)
    except Exception:
        pass
    pdf.set_draw_color(120, 120, 120)
    pdf.line(161, firmas_y, 241, firmas_y)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(161, firmas_y + 2)
    pdf.cell(80, 6, _pdf_safe(FIRMA_STEVEN_NOMBRE), align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(161, firmas_y + 8)
    pdf.cell(80, 5, _pdf_safe(FIRMA_STEVEN_PUESTO), align="C")

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Reporte ejecutivo de NPS (PDF) — ver app_pages/26_NPS.py, botón "📄
# Descargar reporte ejecutivo (PDF)" al final de la pestaña "📊 KPIs". Mismo
# estilo de informe gerencial (franjas azul oscuro + tablas) que ya se usa
# para el Dashboard del Sistema de Tickets, para que ambos reportes se vean
# consistentes si algún día se comparten juntos.
# ---------------------------------------------------------------------------
def nps_reporte_pdf_bytes(
    periodo_texto: str,
    filtro_texto: str,
    resumen_tiendas: list,
    nps_pregunta_texto: str, nps_conteo: dict, nps_total: int, nps_score,
    serv_pregunta_texto: str, serv_conteo: dict, serv_total: int, serv_score,
    opcion_pregunta_texto: str | None, opcion_conteo: dict,
    detalles_otro: list,
    comentarios: list,
    contactos: list,
) -> bytes:
    """Genera el reporte ejecutivo de NPS / satisfacción del cliente como PDF,
    listo para imprimir o adjuntar en un correo a Gerencia / Junta Directiva."""
    from datetime import datetime as _dt

    AZUL_OSCURO = (20, 36, 60)
    GRIS_CLARO = (242, 242, 242)
    GRIS_TEXTO = (90, 90, 90)

    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    def texto_libre_seguro(texto, max_corrida=35):
        """_pdf_safe() ya evita el crash por acentos/emoji, pero fpdf2 también
        puede fallar ('Not enough horizontal space to render a single
        character') si el texto trae una sola 'palabra' -- sin espacios --
        más larga que el ancho disponible (por ejemplo, un cliente que pegó
        una URL larga o una racha de caracteres repetidos en el comentario
        libre de la encuesta). Como esto es texto que escribe el cliente
        final y no se puede controlar, aquí se le insertan espacios cada
        `max_corrida` caracteres a cualquier corrida sin espacios, para que
        fpdf2 siempre pueda partir la línea."""
        texto = _pdf_safe(texto)
        palabras = texto.split(" ")
        arregladas = []
        for palabra in palabras:
            if len(palabra) > max_corrida:
                trozos = [palabra[i:i + max_corrida] for i in range(0, len(palabra), max_corrida)]
                palabra = " ".join(trozos)
            arregladas.append(palabra)
        return " ".join(arregladas)

    # -- Encabezado -- (sin logo, mismo estilo que el informe de KPIs de
    # Sistema de Tickets -- el título arranca directo en el margen izquierdo).
    pdf.set_xy(10, 10)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*AZUL_OSCURO)
    pdf.cell(0, 7, _pdf_safe("Informe Ejecutivo — NPS y Satisfacción del Cliente"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*GRIS_TEXTO)
    pdf.cell(0, 6, _pdf_safe(f"{EMPRESA_NOMBRE} · Periodo: {periodo_texto}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, _pdf_safe(f"Filtro: {filtro_texto}"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(10, 32)
    pdf.set_draw_color(*AZUL_OSCURO)
    pdf.set_line_width(0.6)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    def franja_titulo(texto):
        pdf.set_x(10)
        pdf.set_fill_color(*AZUL_OSCURO)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _pdf_safe(f"  {texto}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    def tabla(encabezados, filas, anchos):
        pdf.set_x(10)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_fill_color(*GRIS_CLARO)
        for texto, ancho in zip(encabezados, anchos):
            pdf.cell(ancho, 7, _pdf_safe(texto), border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9.5)
        for fila_datos in filas:
            pdf.set_x(10)
            for valor, ancho in zip(fila_datos, anchos):
                pdf.cell(ancho, 7, _pdf_safe(valor), border=1, align="C")
            pdf.ln()
        pdf.ln(4)

    def pct(valor, total):
        return f"{(valor / total * 100):.1f}%" if total else "0.0%"

    # -- Calificación promedio por tienda (histórico, no cambia con el filtro) -
    franja_titulo("Calificación promedio por tienda (histórico general)")
    tabla(
        ["Tienda", "Promedio (de 3.0)", "Categoría", "Respuestas"],
        [
            [
                r["tienda"],
                f"{r['promedio']:.1f}" if r["promedio"] is not None else "—",
                r["categoria_label"],
                r["total"],
            ]
            for r in resumen_tiendas
        ],
        [65, 45, 45, 35],
    )

    # -- NPS --------------------------------------------------------------------
    franja_titulo(texto_libre_seguro(f"NPS — {nps_pregunta_texto}"))
    if nps_total:
        tabla(
            ["Total respuestas", "Detractores", "Neutros", "Promotores", "Score NPS"],
            [[
                nps_total,
                f"{nps_conteo.get('detractor', 0)} ({pct(nps_conteo.get('detractor', 0), nps_total)})",
                f"{nps_conteo.get('neutro', 0)} ({pct(nps_conteo.get('neutro', 0), nps_total)})",
                f"{nps_conteo.get('promotor', 0)} ({pct(nps_conteo.get('promotor', 0), nps_total)})",
                nps_score,
            ]],
            [38, 40, 38, 40, 34],
        )
    else:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GRIS_TEXTO)
        pdf.cell(0, 6, _pdf_safe("No hay respuestas todavía para este filtro."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # -- Satisfacción del servicio ----------------------------------------------
    franja_titulo(texto_libre_seguro(f"Satisfacción del servicio — {serv_pregunta_texto}"))
    if serv_total:
        tabla(
            ["Total respuestas", "Detractores", "Neutros", "Promotores", "Índice"],
            [[
                serv_total,
                f"{serv_conteo.get('detractor', 0)} ({pct(serv_conteo.get('detractor', 0), serv_total)})",
                f"{serv_conteo.get('neutro', 0)} ({pct(serv_conteo.get('neutro', 0), serv_total)})",
                f"{serv_conteo.get('promotor', 0)} ({pct(serv_conteo.get('promotor', 0), serv_total)})",
                serv_score,
            ]],
            [38, 40, 38, 40, 34],
        )
    else:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GRIS_TEXTO)
        pdf.cell(0, 6, _pdf_safe("No hay respuestas todavía para este filtro."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # -- Pregunta de opción múltiple ---------------------------------------------
    if opcion_pregunta_texto:
        franja_titulo(texto_libre_seguro(opcion_pregunta_texto))
        if opcion_conteo:
            tabla(
                ["Opción", "Respuestas"],
                [[op, n] for op, n in opcion_conteo.items()],
                [140, 50],
            )
        else:
            pdf.set_x(10)
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*GRIS_TEXTO)
            pdf.cell(0, 6, _pdf_safe("No hay respuestas todavía para este filtro."), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    if pdf.get_y() > 220:
        pdf.add_page()

    # -- Listados en formato de cuadro (tabla real, no párrafos) -----------------
    # Usa la API de tablas de fpdf2 (con ajuste de línea automático dentro de
    # cada celda), en vez de multi_cell a mano -- se ve compacto como un
    # cuadro de Excel y, de paso, fpdf2 maneja solo el salto de línea largo.
    # texto_libre_seguro() se deja como blindaje extra por si una sola
    # "palabra" (sin espacios) fuera más larga que la celda.
    from fpdf.fonts import FontFace
    encabezado_azul = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL_OSCURO)

    def cuadro_libre(titulo, items, campos, anchos, texto_vacio):
        """campos: lista de (encabezado_columna, llave_del_dict)."""
        franja_titulo(f"{titulo} ({len(items)})")
        if not items:
            pdf.set_x(10)
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*GRIS_TEXTO)
            pdf.cell(0, 6, _pdf_safe(texto_vacio), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)
            return
        pdf.set_x(10)
        pdf.set_font("Helvetica", "", 9)
        # franja_titulo() deja el color de relleno del PDF en azul oscuro (es
        # el de su propia franja) y nunca lo regresa a blanco -- si no se
        # resetea aquí, las FILAS del cuadro (no solo el encabezado) heredan
        # ese azul de fondo con letra blanca, ilegible.
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(0, 0, 0)
        with pdf.table(
            col_widths=anchos,
            headings_style=encabezado_azul,
            text_align=tuple("LEFT" for _ in campos),
            line_height=5,
        ) as tabla_fpdf:
            fila = tabla_fpdf.row()
            for encabezado, _clave in campos:
                fila.cell(_pdf_safe(encabezado))
            for item in items:
                fila = tabla_fpdf.row()
                for _encabezado, clave in campos:
                    fila.cell(texto_libre_seguro(item.get(clave) or "—"))
        pdf.ln(4)

    cuadro_libre(
        "Respuestas 'Otro'", detalles_otro,
        [("Fecha", "Fecha"), ("Respuesta", "¿Cuál?")],
        [40, 150],
        "No hay respuestas 'Otro' en este período.",
    )

    if pdf.get_y() > 220:
        pdf.add_page()

    cuadro_libre(
        "Comentarios de mejora", comentarios,
        [("Fecha", "Fecha"), ("Comentario", "Comentario")],
        [40, 150],
        "No hay comentarios en este período.",
    )

    if pdf.get_y() > 220:
        pdf.add_page()

    cuadro_libre(
        "Contactos para dar seguimiento", contactos,
        [("Fecha", "Fecha"), ("Nombre", "Nombre"), ("Teléfono", "Teléfono"), ("Comentario", "Comentario")],
        [30, 35, 30, 95],
        "Nadie ha dejado sus datos de contacto en este período.",
    )

    pdf.set_x(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(
        0, 5,
        _pdf_safe(
            f"Informe generado automáticamente por la Plataforma Comercial — {EMPRESA_NOMBRE} — "
            f"{_dt.now().strftime('%d/%m/%Y %H:%M')}."
        ),
    )

    return bytes(pdf.output())


def tickets_tienda_reporte_mensual_pdf_bytes(
    periodo_texto: str,
    filtro_texto: str,
    resumen_general: dict,
    comparativo_tiendas: list,
    detalle_tiendas: list,
    motivos_abandono: list,
) -> bytes:
    """Genera el resumen ejecutivo mensual del Sistema de Tickets — Tiendas
    como PDF: un resumen general (todas las tiendas) y el desglose de cada
    tienda por separado, listo para Gerencia / Junta Directiva. Mismo estilo
    que nps_reporte_pdf_bytes (franjas azules + tablas fpdf2)."""
    from datetime import datetime as _dt

    AZUL_OSCURO = (20, 36, 60)
    GRIS_CLARO = (242, 242, 242)
    GRIS_TEXTO = (90, 90, 90)

    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    def texto_libre_seguro(texto, max_corrida=35):
        """Ver nps_reporte_pdf_bytes: evita el crash de fpdf2 cuando un
        motivo de abandono (texto libre escrito por el equipo de tienda)
        trae una 'palabra' sin espacios más larga que la celda."""
        texto = _pdf_safe(texto)
        palabras = texto.split(" ")
        arregladas = []
        for palabra in palabras:
            if len(palabra) > max_corrida:
                trozos = [palabra[i:i + max_corrida] for i in range(0, len(palabra), max_corrida)]
                palabra = " ".join(trozos)
            arregladas.append(palabra)
        return " ".join(arregladas)

    # -- Encabezado --------------------------------------------------------
    pdf.set_xy(10, 10)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*AZUL_OSCURO)
    pdf.cell(0, 7, _pdf_safe("Informe Ejecutivo Mensual — Sistema de Tickets de Tiendas"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*GRIS_TEXTO)
    pdf.cell(0, 6, _pdf_safe(f"{EMPRESA_NOMBRE} · Periodo: {periodo_texto}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, _pdf_safe(f"Filtro: {filtro_texto}"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(10, 32)
    pdf.set_draw_color(*AZUL_OSCURO)
    pdf.set_line_width(0.6)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    def franja_titulo(texto):
        pdf.set_x(10)
        pdf.set_fill_color(*AZUL_OSCURO)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _pdf_safe(f"  {texto}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    def tabla(encabezados, filas, anchos, alineacion="C"):
        pdf.set_x(10)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_fill_color(*GRIS_CLARO)
        for texto, ancho in zip(encabezados, anchos):
            pdf.cell(ancho, 7, _pdf_safe(texto), border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9.5)
        for fila_datos in filas:
            pdf.set_x(10)
            for valor, ancho in zip(fila_datos, anchos):
                pdf.cell(ancho, 7, _pdf_safe(valor), border=1, align=alineacion)
            pdf.ln()
        pdf.ln(4)

    # -- Resumen general (todas las tiendas dentro del filtro) -------------
    franja_titulo("Resumen general del mes")
    tabla(
        ["Tickets", "Facturados", "Abandono", "% Facturado", "Tiempo prom. total", "Espera→Elab.", "Elab.→Facturado"],
        [[
            resumen_general["total"], resumen_general["facturados"], resumen_general["abandono"],
            resumen_general["pct_facturado"], resumen_general["tiempo_prom_total"],
            resumen_general["tiempo_prom_espera"], resumen_general["tiempo_prom_elaboracion"],
        ]],
        [27, 27, 27, 27, 32, 27, 33],
    )

    # -- Comparativo por tienda ----------------------------------------------
    franja_titulo("Comparativo por tienda")
    if comparativo_tiendas:
        tabla(
            ["Tienda", "Tickets", "Facturados", "Abandono", "% Facturado", "Tiempo prom. total"],
            [[
                c["tienda"], c["total"], c["facturados"], c["abandono"], c["pct_facturado"], c["tiempo_prom_total"],
            ] for c in comparativo_tiendas],
            [50, 27, 30, 27, 30, 36],
        )
    else:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GRIS_TEXTO)
        pdf.cell(0, 6, _pdf_safe("No hay tickets registrados en este período."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # -- Detalle por tienda ---------------------------------------------------
    for det in detalle_tiendas:
        if pdf.get_y() > 220:
            pdf.add_page()
        franja_titulo(f"🏬 {det['tienda']}")
        tabla(
            ["Espera → Elaboración", "Elaboración → Facturado"],
            [[det["espera_texto"], det["elaboracion_texto"]]],
            [95, 105],
        )
        pdf.set_x(10)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(0, 6, _pdf_safe("Servicios/productos más solicitados"), new_x="LMARGIN", new_y="NEXT")
        if det["top_servicios"]:
            tabla(
                ["Servicio/producto", "Tickets"],
                [[nombre, cantidad] for nombre, cantidad in det["top_servicios"]],
                [160, 40],
                alineacion="L",
            )
        else:
            pdf.set_x(10)
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*GRIS_TEXTO)
            pdf.cell(0, 6, _pdf_safe("Sin tickets en este período."), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    if pdf.get_y() > 220:
        pdf.add_page()

    # -- Motivos de abandono del mes (cuadro, mismo patrón que NPS) ---------
    from fpdf.fonts import FontFace
    encabezado_azul = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL_OSCURO)

    franja_titulo(f"Motivos de abandono ({len(motivos_abandono)})")
    if not motivos_abandono:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GRIS_TEXTO)
        pdf.cell(0, 6, _pdf_safe("No hubo tickets marcados como Abandono en este período."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)
    else:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "", 9)
        # franja_titulo() deja el color de relleno en azul oscuro y no lo
        # regresa a blanco -- si no se resetea aquí, las FILAS del cuadro
        # (no solo el encabezado) heredan ese azul de fondo, ilegible.
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(0, 0, 0)
        campos = [("Tienda", "Tienda"), ("Fecha", "Fecha"), ("Cliente", "Cliente"), ("Motivo", "Motivo")]
        with pdf.table(
            col_widths=[30, 25, 45, 90],
            headings_style=encabezado_azul,
            text_align=tuple("LEFT" for _ in campos),
            line_height=5,
        ) as tabla_fpdf:
            fila = tabla_fpdf.row()
            for encabezado, _clave in campos:
                fila.cell(_pdf_safe(encabezado))
            for item in motivos_abandono:
                fila = tabla_fpdf.row()
                for _encabezado, clave in campos:
                    fila.cell(texto_libre_seguro(item.get(clave) or "—"))
        pdf.ln(4)

    pdf.set_x(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(
        0, 5,
        _pdf_safe(
            f"Informe generado automáticamente por la Plataforma Comercial — {EMPRESA_NOMBRE} — "
            f"{_dt.now().strftime('%d/%m/%Y %H:%M')}."
        ),
    )

    return bytes(pdf.output())
