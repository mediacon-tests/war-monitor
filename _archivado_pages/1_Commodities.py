from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from utiles.config import cargar
from utiles.ui import inject_css, status_bar, panel_footer, chip, kpi_card, safe
from utiles.plot_theme import PALETA, aplicar
from fuentes.precios import (
    serie_historica, cotizacion_actual, hormuz_stress_index,
)

st.set_page_config(page_title="Commodities — War Monitor", page_icon="📊", layout="wide")
inject_css()
st_autorefresh(interval=300_000, key="auto_comm")

cfg = cargar("commodities.yaml")

with st.sidebar:
    st.markdown("### Commodities")
    dias = st.slider("Ventana", 30, 730, 180, step=30)

# Status bar — calcular nivel basado en datos de la página
brent_q = cotizacion_actual("BZ=F")
wti_q = cotizacion_actual("CL=F")
nivel_pag = "ELEVATED"
sub_pag = "Mercados de energía · yfinance"
if brent_q and abs(brent_q["variacion_pct"]) >= 5:
    nivel_pag = "HIGH"
    sub_pag = f"Brent {brent_q['variacion_pct']:+.1f}%"

status_bar(nivel_pag, sub_pag)
st.markdown("# Commodities")

# --- HERO: Brent / WTI / Spread ---
hero_cols = st.columns([1, 1, 1])

with hero_cols[0]:
    if brent_q:
        chip_html = chip("CRUDE STRESS", "stress") if abs(brent_q["variacion_pct"]) >= 3 else ""
        st.markdown(kpi_card(
            "BRENT (ICE)", f"${brent_q['precio']:.2f}",
            f"{brent_q['variacion_pct']:+.2f}%", "USD/bbl",
            color_borde=PALETA["ambar"], chip_html=chip_html, tamano="xl",
        ), unsafe_allow_html=True)
with hero_cols[1]:
    if wti_q:
        st.markdown(kpi_card(
            "WTI (NYMEX)", f"${wti_q['precio']:.2f}",
            f"{wti_q['variacion_pct']:+.2f}%", "USD/bbl",
            color_borde=PALETA["azul"], tamano="xl",
        ), unsafe_allow_html=True)
with hero_cols[2]:
    if wti_q and brent_q:
        spread = wti_q["precio"] - brent_q["precio"]
        prev = wti_q["previo"] - brent_q["previo"] if (wti_q["previo"] and brent_q["previo"]) else 0
        delta_sp = spread - prev
        chip_sp = chip("DISLOC", "disrupt") if (spread > 3 or spread < -10) else ""
        st.markdown(kpi_card(
            "WTI–BRENT ARB", f"${spread:+.2f}", f"{delta_sp:+.2f} hoy",
            "diferencial USD/bbl", color_borde=PALETA["violeta"],
            chip_html=chip_sp, tamano="xl",
        ), unsafe_allow_html=True)

st.markdown("")

# --- Chart hero: Brent + WTI arriba, Spread abajo (subplot, no overlay) ---
brent_h = serie_historica("BZ=F", dias=dias)
wti_h = serie_historica("CL=F", dias=dias)

if not brent_h.empty and not wti_h.empty:
    merged = brent_h.merge(wti_h, on="fecha", suffixes=("_brent", "_wti"))
    merged["spread"] = merged["cierre_wti"] - merged["cierre_brent"]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.04,
    )
    fig.add_trace(go.Scatter(
        x=merged["fecha"], y=merged["cierre_brent"],
        name="Brent", line=dict(color=PALETA["ambar"], width=2.5),
        hovertemplate="Brent<br>%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=merged["fecha"], y=merged["cierre_wti"],
        name="WTI", line=dict(color=PALETA["azul"], width=2.5),
        hovertemplate="WTI<br>%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=merged["fecha"], y=merged["spread"],
        name="WTI–Brent", line=dict(color=PALETA["violeta"], width=1.8),
        fill="tozeroy", fillcolor="rgba(139,111,184,0.15)",
        hovertemplate="Spread<br>%{x|%Y-%m-%d}<br>$%{y:+.2f}<extra></extra>",
        showlegend=False,
    ), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=PALETA["borde"], width=1), row=2, col=1)

    fig.update_yaxes(title_text="USD/bbl", row=1, col=1, gridcolor=PALETA["fondo_elev"])
    fig.update_yaxes(title_text="Spread", row=2, col=1, gridcolor=PALETA["fondo_elev"])
    fig.update_xaxes(gridcolor=PALETA["fondo_elev"], row=1, col=1)
    fig.update_xaxes(gridcolor=PALETA["fondo_elev"], row=2, col=1)
    fig.update_layout(
        height=460, hovermode="x unified",
        paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
        font=dict(family="Inter", color=PALETA["texto"], size=12),
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=PALETA["texto_2"])),
        hoverlabel=dict(bgcolor=PALETA["fondo_elev"], bordercolor=PALETA["borde"],
                        font=dict(family="JetBrains Mono", size=11, color=PALETA["texto"])),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# --- Hormuz Stress Index ---
st.markdown("")
st.markdown("### Hormuz Stress Index (HSI)")
st.caption(
    "Composición de z-scores rolling 90d (`min_periods=60`): "
    "^OVX (vol crudo), ^VIX, TLT proxy MOVE en niveles + Brent y Oro en log-retornos 5d. "
    "Valores >+1.5 = mercado pricing event, >+2 = stress agudo."
)

ovx_h = serie_historica("^OVX", dias=max(dias, 365))
gold_h = serie_historica("GC=F", dias=max(dias, 365))
vix_h = serie_historica("^VIX", dias=max(dias, 365))
tlt_h = serie_historica("TLT", dias=max(dias, 365))
brent_h_long = serie_historica("BZ=F", dias=max(dias, 365))

hsi = hormuz_stress_index(ovx_h, brent_h_long, gold_h, vix_h, tlt_h)
if not hsi.empty:
    desde = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=dias)
    hsi_recent = hsi[hsi["fecha"] >= desde].copy()
    fig_hsi = go.Figure()
    color_fill = [
        PALETA["rojo"] if v >= 1.5 else PALETA["naranja"] if v >= 0.5
        else PALETA["azul"] if v >= -0.5 else PALETA["verde"]
        for v in hsi_recent["HSI"].fillna(0)
    ]
    fig_hsi.add_trace(go.Bar(
        x=hsi_recent["fecha"], y=hsi_recent["HSI"],
        marker_color=color_fill,
        name="HSI",
        hovertemplate="%{x|%Y-%m-%d}<br>HSI: %{y:+.2f}<extra></extra>",
    ))
    fig_hsi.add_hline(y=1.5, line=dict(color=PALETA["rojo"], width=1, dash="dash"))
    fig_hsi.add_hline(y=-1.5, line=dict(color=PALETA["verde"], width=1, dash="dash"))
    fig_hsi.add_hline(y=0, line=dict(color=PALETA["borde"], width=1))
    aplicar(fig_hsi, height=280, hovermode="x",
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"])
    st.plotly_chart(fig_hsi, use_container_width=True, config={"displayModeBar": False})

    if not hsi_recent.empty:
        ult = hsi_recent["HSI"].iloc[-1]
        n_comp = int(hsi_recent["n_componentes"].iloc[-1])
        if pd.notna(ult):
            if ult >= 1.5:
                cls = chip("STRESS AGUDO", "disrupt")
            elif ult >= 0.5:
                cls = chip("ELEVADO", "stress")
            else:
                cls = chip("NORMAL", "ok")
            st.markdown(
                f"**HSI actual: {ult:+.2f}** {cls} · {n_comp}/5 componentes activos",
                unsafe_allow_html=True,
            )

st.markdown("")

# --- Tabs secundarias ---
tabs = st.tabs([
    "Destilados / gas",
    "Petroquímicos",
    "Fertilizantes",
    "Fletes (tankers)",
    "Refinerías",
    "LNG",
    "Defensa",
    "Macro",
])

grupos = [
    ("destilados_y_gas", tabs[0]),
    ("petroquimicos", tabs[1]),
    ("fertilizantes", tabs[2]),
    ("fletes_tankers", tabs[3]),
    ("refinerias_expuestas", tabs[4]),
    ("lng_y_gas_global", tabs[5]),
    ("defensa", tabs[6]),
    ("macro_hedge", tabs[7]),
]


def render_grupo_tabla(items: list[dict], dias: int):
    """Tabla densa con sparklines como segunda lectura."""
    if not items:
        st.info("Sin items en esta categoría.")
        return

    # Recolectar series
    rows = []
    series_dict = {}
    for it in items:
        c = cotizacion_actual(it["ticker"])
        s = serie_historica(it["ticker"], dias=dias)
        if not s.empty:
            series_dict[it["ticker"]] = s
        rows.append({
            "Nombre": it["nombre"],
            "Ticker": it["ticker"],
            "Unidad": it.get("unidad", ""),
            "Precio": c["precio"] if c else None,
            "Var %": c["variacion_pct"] if c else None,
            "Sparkline": series_dict[it["ticker"]]["cierre"].tail(30).tolist()
                         if it["ticker"] in series_dict else [],
        })
    df_t = pd.DataFrame(rows)

    st.dataframe(
        df_t, use_container_width=True, hide_index=True,
        column_config={
            "Precio": st.column_config.NumberColumn(format="%.2f"),
            "Var %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Sparkline": st.column_config.LineChartColumn(
                "30d sparkline", y_min=None, y_max=None, width="medium",
            ),
            "Ticker": st.column_config.TextColumn(width="small"),
            "Unidad": st.column_config.TextColumn(width="small"),
        },
    )

    # Chart normalizado debajo
    if series_dict:
        fig = go.Figure()
        for it in items:
            tk = it["ticker"]
            if tk not in series_dict:
                continue
            s = series_dict[tk]
            primer = s["cierre"].iloc[0]
            if primer == 0:
                continue
            fig.add_trace(go.Scatter(
                x=s["fecha"], y=s["cierre"] / primer * 100, mode="lines",
                name=it["nombre"][:32], line=dict(width=1.5),
                hovertemplate=f"{safe(it['nombre'])}<br>%{{x|%Y-%m-%d}}<br>%{{y:.1f}}<extra></extra>",
            ))
        aplicar(fig, height=320, hovermode="x unified",
                yaxis_title="Índice base 100",
                paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


for clave, tab in grupos:
    with tab:
        render_grupo_tabla(cfg.get(clave, []), dias)

panel_footer(
    "Yahoo Finance · series spot delayed 15-20m",
    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
)
