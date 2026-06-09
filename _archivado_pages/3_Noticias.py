import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

from utiles.config import cargar
from utiles.ui import (
    inject_css, status_bar, panel_footer, chip, hace_cuanto, status_dot,
    kpi_card, safe,
)
from utiles.plot_theme import PALETA, aplicar
from fuentes.rss import fetch_todos as fetch_rss, filtrar_keywords, estado_feeds
from fuentes.gdelt import construir_query, buscar_articulos, timeline_volumen

st.set_page_config(page_title="Noticias — War Monitor", page_icon="📰", layout="wide")
inject_css()
st_autorefresh(interval=600_000, key="auto_news")

feeds_cfg = cargar("feeds_rss.yaml").get("feeds", [])
kws_cfg = cargar("keywords.yaml")
buckets_disponibles = list(kws_cfg.keys())

with st.sidebar:
    st.markdown("### Noticias")
    incluir_rss = st.checkbox("RSS (estable)", value=True)
    incluir_gdelt = st.checkbox("GDELT (lento)", value=True)
    timespan_gdelt = st.selectbox("Ventana GDELT", ["1d", "3d", "7d"], index=1)
    buckets_seleccionados = st.multiselect(
        "Categorías", buckets_disponibles,
        default=["ataques_a_refinerias", "incidentes_tanqueros", "actores_clave"],
    )
    solo_destacados = st.checkbox("Solo ataques a refinerías", value=False)

# Fetch RSS
df_rss = pd.DataFrame()
if incluir_rss:
    with st.spinner("Cargando RSS…"):
        df_rss = fetch_rss(feeds_cfg)
    if not df_rss.empty:
        df_rss = filtrar_keywords(df_rss, kws_cfg)

# Fetch GDELT
df_gdelt = pd.DataFrame()
df_timeline = pd.DataFrame()
query = ""
if incluir_gdelt and buckets_seleccionados:
    query = construir_query(buckets_seleccionados, kws_cfg, max_terminos=10)
    with st.spinner("Cargando GDELT…"):
        df_gdelt = buscar_articulos(query, timespan=timespan_gdelt, max_records=100)
        df_timeline = timeline_volumen(query, timespan="30d")
    if not df_gdelt.empty:
        df_gdelt = df_gdelt.copy()
        df_gdelt["resumen"] = ""
        df_gdelt["categorias"] = [["GDELT"] for _ in range(len(df_gdelt))]
        df_gdelt["es_ataque_refineria"] = df_gdelt["titulo"].fillna("").str.lower().str.contains(
            r"refinery|refineria", regex=True, na=False,
        )
        df_gdelt["peso_relevancia"] = 0.7

# Merge robusto: tz UTC en ambos, columnas comunes
def normalizar_tz(d: pd.DataFrame) -> pd.DataFrame:
    if d.empty or "fecha" not in d.columns:
        return d
    d = d.copy()
    d["fecha"] = pd.to_datetime(d["fecha"], utc=True, errors="coerce")
    return d.dropna(subset=["fecha"])


df_rss = normalizar_tz(df_rss)
df_gdelt = normalizar_tz(df_gdelt)

dfs_unidos = [d for d in [df_rss, df_gdelt] if not d.empty]
if dfs_unidos:
    # Asegurar que todas tengan las columnas usadas más adelante
    for d in dfs_unidos:
        for col in ("categorias", "es_ataque_refineria"):
            if col not in d.columns:
                d[col] = pd.Series([[]] * len(d) if col == "categorias" else [False] * len(d))
    df = pd.concat(dfs_unidos, ignore_index=True, sort=False)
    if buckets_seleccionados and incluir_rss:
        def matchea(row):
            if row.get("tipo_fuente") == "GDELT":
                return True
            cats = row.get("categorias") or []
            if not isinstance(cats, list):
                return False
            return any(b in cats for b in buckets_seleccionados)

        df = df[df.apply(matchea, axis=1)].reset_index(drop=True)
else:
    df = pd.DataFrame()

# Status bar dinámico
nivel_pag = "ELEVATED"
sub_pag = "Inteligencia abierta · GDELT + RSS"
if not df.empty and "es_ataque_refineria" in df.columns:
    n_ataques_72h = int(
        df[
            df["es_ataque_refineria"]
            & (df["fecha"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=72))
        ].shape[0]
    )
    if n_ataques_72h > 0:
        nivel_pag = "CRITICAL"
        sub_pag = f"{n_ataques_72h} ataques a refinerías en 72h"

status_bar(nivel_pag, sub_pag)
st.markdown("# Noticias y eventos")

# --- KPIs ---
col1, col2, col3, col4 = st.columns(4)
n_total = len(df) if not df.empty else 0
n_ataques = int(df["es_ataque_refineria"].sum()) if (not df.empty and "es_ataque_refineria" in df.columns) else 0
fuentes_unicas = df["fuente"].nunique() if not df.empty else 0
ult_str = "—"
ult_ts = ""
if not df.empty:
    ult = df["fecha"].max()
    if pd.notna(ult):
        ult_str = hace_cuanto(ult)
        ult_ts = ult.strftime("%Y-%m-%d %H:%M UTC")

col1.markdown(kpi_card(
    f"Items {timespan_gdelt}", str(n_total), None, "RSS + GDELT",
    color_borde=PALETA["azul"],
), unsafe_allow_html=True)

chip_atq = chip("ALERTA", "disrupt") if n_ataques else ""
col2.markdown(kpi_card(
    "Ataques refinerías", str(n_ataques), None, "items destacados",
    color_borde=PALETA["rojo"], chip_html=chip_atq,
), unsafe_allow_html=True)

col3.markdown(kpi_card(
    "Fuentes activas", str(fuentes_unicas), None, "RSS + GDELT",
    color_borde=PALETA["violeta"],
), unsafe_allow_html=True)

col4.markdown(kpi_card(
    "Último item", ult_str, None, ult_ts,
    color_borde=PALETA["ambar"],
), unsafe_allow_html=True)

st.markdown("")

# --- Tabs ---
tab_eventos, tab_timeline, tab_health = st.tabs(["Eventos", "Timeline (GDELT)", "Estado fuentes"])

with tab_eventos:
    if df.empty:
        st.info("Sin items que matcheen los filtros actuales.")
    else:
        df_show = df.copy()
        if solo_destacados:
            df_show = df_show[df_show["es_ataque_refineria"]]
        df_show = df_show.sort_values("fecha", ascending=False).head(80)

        cards_html = []
        for _, r in df_show.iterrows():
            ts = r["fecha"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if pd.notna(ts) else ""
            hace = hace_cuanto(ts) if pd.notna(ts) else ""
            url = safe(r.get("url", ""))
            titulo = safe((r.get("titulo") or "")[:200])
            fuente = safe(r.get("fuente", ""))
            cats = r.get("categorias") or []
            if not isinstance(cats, list):
                cats = []
            cats_chips = " ".join(
                chip(c.upper().replace("_", " ")[:18], "disrupt" if c == "ataques_a_refinerias" else "info")
                for c in cats[:3]
            )
            link = f'<a href="{url}" target="_blank" style="color:#E6EAF2;text-decoration:none;">{titulo}</a>' if url else titulo

            if r.get("es_ataque_refineria"):
                cards_html.append(f"""
                <div class="alerta-refineria">
                  <div class="alerta-titulo">{link}</div>
                  <div class="alerta-meta">{fuente} · {ts_str} · {hace} {cats_chips}</div>
                </div>
                """)
            else:
                cards_html.append(f"""
                <div class="panel" style="padding:8px 12px;margin-bottom:6px;">
                  <div style="color:#E6EAF2;font-size:13px;font-weight:500;">{link}</div>
                  <div style="color:#6B7280;font-size:10px;font-family:'JetBrains Mono',monospace;margin-top:4px;">
                    {fuente} · {ts_str} · {hace} {cats_chips}
                  </div>
                </div>
                """)
        st.markdown("".join(cards_html), unsafe_allow_html=True)

with tab_timeline:
    if df_timeline.empty:
        st.info("Sin timeline de GDELT (probar con query distinta o esperar).")
    else:
        df_timeline = df_timeline.sort_values("fecha")
        df_timeline["ma7"] = df_timeline["volumen"].rolling(7, min_periods=1).mean()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_timeline["fecha"], y=df_timeline["volumen"],
            name="Volumen diario", marker_color=PALETA["azul"], opacity=0.5,
        ))
        fig.add_trace(go.Scatter(
            x=df_timeline["fecha"], y=df_timeline["ma7"],
            name="MA 7d", mode="lines", line=dict(color=PALETA["ambar"], width=2.5),
        ))
        aplicar(fig, height=380, hovermode="x unified",
                paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption(f"Volumen diario de artículos GDELT que matchean: `{safe(query[:120])}…`")

with tab_health:
    st.markdown("##### Estado de feeds RSS")
    estados = estado_feeds(feeds_cfg)
    rows_html = ""
    for e in estados:
        ts_str = ""
        if e.get("ult_fecha") is not None and pd.notna(e["ult_fecha"]):
            ts_str = e["ult_fecha"].strftime("%Y-%m-%d %H:%M UTC")
        rows_html += (
            f'<div class="health-row">{status_dot(e["estado"])}'
            f'<span class="nombre">{safe(e["nombre"])}</span>'
            f'<span class="ts">{safe(ts_str)}</span></div>'
        )
    st.markdown(rows_html, unsafe_allow_html=True)

panel_footer("GDELT DOC 2.0 · feeds RSS")
