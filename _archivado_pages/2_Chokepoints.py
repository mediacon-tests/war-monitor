import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

from utiles.config import cargar
from utiles.ui import inject_css, status_bar, panel_footer, chip, kpi_card, safe
from utiles.plot_theme import PALETA, aplicar
from fuentes.chokepoints import fetch_transitos, resumen_vs_baseline, calcular_estado

st.set_page_config(page_title="Chokepoints — War Monitor", page_icon="⚓", layout="wide")
inject_css()
st_autorefresh(interval=900_000, key="auto_choke")

cfg = cargar("chokepoints.yaml")["chokepoints"]
portids = [c["portid"] for c in cfg]
nombre_por_id = {c["portid"]: c["nombre_corto"] for c in cfg}
color_por_id = {c["portid"]: c["color"] for c in cfg}

with st.sidebar:
    st.markdown("### Chokepoints")
    dias = st.slider("Ventana", min_value=60, max_value=730, value=180, step=30)
    metric = st.radio("Métrica", ["Tanqueros (n_tanker)", "Capacidad (DWT)"], index=0)
    metric_col = "n_tanker" if metric.startswith("Tanq") else "capacity_tanker"
    ventana_actual = st.slider("Días para 'actual'", 3, 30, 7)

with st.spinner("Cargando PortWatch…"):
    df = fetch_transitos(portids, dias=dias)

if df.empty:
    status_bar("ELEVATED", "Tránsito de tanqueros · IMF PortWatch")
    st.markdown("# Chokepoints")
    st.error("Sin datos de PortWatch (verificar conectividad).")
    st.stop()

resumen = resumen_vs_baseline(df, ventana_actual=ventana_actual)
ult_fecha = df["fecha"].max()
lag_dias = int((pd.Timestamp.now(tz="UTC").normalize() - ult_fecha.normalize()).days)

# Status bar dinámico: si hay disrupt severo y lag aceptable → HIGH
nivel_pag = "ELEVATED"
sub_pag = f"PortWatch · lag {lag_dias}d"
if not resumen.empty:
    peor = resumen.dropna(subset=["z_score"]).sort_values("z_score")
    if not peor.empty and peor.iloc[0]["z_score"] <= -2.0 and lag_dias <= 10:
        nivel_pag = "HIGH"
        sub_pag = f"{peor.iloc[0]['portname']} z={peor.iloc[0]['z_score']:.1f} · lag {lag_dias}d"

status_bar(nivel_pag, sub_pag)
st.markdown("# Chokepoints — Hormuz · Suez · Bab el-Mandeb")
if lag_dias > 7:
    st.warning(
        f"⚠ Datos publicados con lag de **{lag_dias} días**. PortWatch actualiza martes ~9am ET. "
        f"El 'actual' refleja la ventana hasta **{ult_fecha.strftime('%Y-%m-%d')}**, no hoy."
    )

# --- KPI strip ---
cols = st.columns(len(cfg))
for i, c in enumerate(cfg):
    fila = resumen[resumen["portid"] == c["portid"]]
    if fila.empty:
        with cols[i]:
            st.markdown(kpi_card(
                c["nombre_corto"], "s/d", None, "sin datos",
                color_borde=PALETA["borde"], tamano="xl",
            ), unsafe_allow_html=True)
        continue
    f = fila.iloc[0]
    desvio = f["desvio_pct"] if pd.notna(f["desvio_pct"]) else 0
    z = f["z_score"]
    chip_html = ""
    if pd.notna(z):
        if z <= -2.0:
            chip_html = chip("DISRUPTION", "disrupt")
        elif z <= -1.0:
            chip_html = chip("BELOW", "stress")
        elif z >= 2.0:
            chip_html = chip("HIGH FLOW", "info")

    z_text = f"{z:.2f}" if pd.notna(z) else "—"

    with cols[i]:
        st.markdown(kpi_card(
            c["nombre_corto"],
            f"{f['actual']:.1f}",
            f"{desvio:+.1f}% vs baseline",
            f"{ventana_actual}d · base 90d · z={z_text}",
            color_borde=c["color"], chip_html=chip_html, tamano="xl",
        ), unsafe_allow_html=True)

# --- Gráfico principal ---
st.markdown("")
st.markdown("### Tránsito diario · media móvil 7d")
mostrar_raw = st.checkbox("Mostrar serie cruda (con ruido diario)", value=False)

fig = go.Figure()
for c in cfg:
    g = df[df["portid"] == c["portid"]].sort_values("fecha")
    if g.empty:
        continue
    g[f"{metric_col}_ma7"] = g[metric_col].rolling(7, min_periods=1).mean()
    if mostrar_raw:
        fig.add_trace(go.Scatter(
            x=g["fecha"], y=g[metric_col],
            name=c["nombre_corto"] + " (raw)", mode="lines",
            line=dict(width=0.6, color=c["color"]),
            opacity=0.30, showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.0f}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=g["fecha"], y=g[f"{metric_col}_ma7"],
        name=c["nombre_corto"], mode="lines",
        line=dict(width=2.5, color=c["color"]),
        hovertemplate=safe(c["nombre_corto"]) + "<br>%{x|%Y-%m-%d}<br>MA7: %{y:.1f}<extra></extra>",
    ))

aplicar(fig, height=440, hovermode="x unified", xaxis_title=None,
        yaxis_title=metric.split(" ")[0],
        paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"))
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
st.caption(
    f"Última actualización del dataset: **{ult_fecha.strftime('%Y-%m-%d')}**. "
    f"Baseline = mediana de mismos días-de-semana últimos 90d (robusto a outliers vía MAD)."
)

# --- Tabla expandible ---
with st.expander("Ver últimos 30 días por chokepoint"):
    for c in cfg:
        g = df[df["portid"] == c["portid"]].sort_values("fecha", ascending=False).head(30).copy()
        if g.empty:
            continue
        st.markdown(f"**{safe(c['nombre'])}**")
        g["fecha"] = g["fecha"].dt.strftime("%Y-%m-%d")
        st.dataframe(
            g[["fecha", "n_tanker", "n_total", "tanker_share", "capacity_tanker"]]
              .rename(columns={
                  "fecha": "Fecha",
                  "n_tanker": "Tanqueros",
                  "n_total": "Total buques",
                  "tanker_share": "Share tanker",
                  "capacity_tanker": "DWT tanker",
              }),
            use_container_width=True, hide_index=True,
            column_config={
                "Share tanker": st.column_config.NumberColumn(format="%.2f"),
                "DWT tanker": st.column_config.NumberColumn(format="%.0f"),
            },
        )

panel_footer("IMF PortWatch · Daily Chokepoints", ult_fecha.strftime("%Y-%m-%d"))
