"""War Monitor — dashboard único minimalista."""
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from utiles.config import cargar
from utiles.ui import (
    inject_css, app_header, kpi, chip, hace_cuanto, health_row, safe,
    section_desc, brief,
)
from utiles.plot_theme import PALETA, aplicar
from fuentes.precios import cotizacion_actual, serie_historica, hormuz_stress_index
from fuentes.reservas import (
    spr_usa_semanal, snapshot_global, series_historicas, ultima_fecha_jodi,
)
from fuentes.lng import (
    gas_usa_semanal, snapshot_global_gas, series_historicas_gas, ultima_fecha_gas,
)
from fuentes.chokepoints import fetch_transitos, resumen_vs_baseline
from fuentes.rss import fetch_todos as fetch_rss, filtrar_keywords
from fuentes.gdelt import construir_query, buscar_articulos
from fuentes.bluesky import fetch_todas_cuentas, filtrar_relevantes
from fuentes.sentiment import aplicar_sentiment, score_global, agregar_ponderado
from fuentes.sentiment_claude import aplicar_sentiment_claude, claude_disponible
from fuentes.resumen_ai import generar_resumen

st.set_page_config(
    page_title="War Monitor",
    page_icon="○",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={},
)
inject_css()
st_autorefresh(interval=120_000, key="auto_dash")  # 2 min

# session_key: cambia con F5 / botón Regenerar. Cualquier cosa cacheada por sesión
# (resumen IA, sentiment Claude) se reutiliza dentro de la misma session_key.
if "ai_session_key" not in st.session_state:
    st.session_state.ai_session_key = int(datetime.now(timezone.utc).timestamp())
SESSION_KEY = st.session_state.ai_session_key

# ─── Cargas (todas cacheadas) ───────────────────────────────────────────────
brent = cotizacion_actual("BZ=F")
wti = cotizacion_actual("CL=F")
ovx = cotizacion_actual("^OVX")
gold = cotizacion_actual("GC=F")

brent_h60 = serie_historica("BZ=F", dias=60)
wti_h60 = serie_historica("CL=F", dias=60)

cps_cfg = cargar("chokepoints.yaml").get("chokepoints", [])
df_cp = fetch_transitos([c["portid"] for c in cps_cfg], dias=180)
resumen_cp = resumen_vs_baseline(df_cp) if not df_cp.empty else pd.DataFrame()

feeds_cfg = cargar("feeds_rss.yaml").get("feeds", [])
kws_cfg = cargar("keywords.yaml")
df_rss = fetch_rss(feeds_cfg)
if not df_rss.empty:
    df_rss = filtrar_keywords(df_rss, kws_cfg)

q = construir_query(["ataques_a_refinerias", "incidentes_tanqueros"], kws_cfg, max_terminos=8)
df_gdelt = buscar_articulos(q, timespan="3d", max_records=50)

cuentas_cfg = cargar("cuentas_bluesky.yaml")
df_bsky_raw = fetch_todas_cuentas(cuentas_cfg, limit_por_cuenta=30)
n_posts_total = len(df_bsky_raw)
df_bsky = filtrar_relevantes(df_bsky_raw, kws_cfg) if not df_bsky_raw.empty else df_bsky_raw
n_posts_relevantes = len(df_bsky)
score_data = {"score": 0.0, "n_posts": 0, "n_cuentas": 0, "n_descartados_lang": 0}
sentiment_modelo = "VADER"
if not df_bsky.empty:
    if claude_disponible():
        df_bsky = aplicar_sentiment_claude(df_bsky, session_key=SESSION_KEY)
        sentiment_modelo = "claude-haiku-4-5"
        # Si Claude clasificó TODO como neutro (NaN), no hay señal; fallback a VADER.
        if df_bsky["score"].notna().sum() == 0 and len(df_bsky) > 5:
            df_bsky = aplicar_sentiment(df_bsky, columna_texto="texto", solo_ingles=True)
            sentiment_modelo = "VADER (fallback: Claude no clasificó nada)"
    else:
        df_bsky = aplicar_sentiment(df_bsky, columna_texto="texto", solo_ingles=True)
        sentiment_modelo = "VADER (sin ANTHROPIC_API_KEY)"
    # score_global ya descarta NaN: la ponderación 2-step (media por cuenta →
    # promedio ponderado por peso de la cuenta) opera solo sobre posts con score válido.
    score_data = score_global(df_bsky, ventana_horas=24)

# Series largas para HSI
ovx_long = serie_historica("^OVX", dias=400)
gold_long = serie_historica("GC=F", dias=400)
vix_long = serie_historica("^VIX", dias=400)
tlt_long = serie_historica("TLT", dias=400)
brent_long = serie_historica("BZ=F", dias=400)
hsi = hormuz_stress_index(ovx_long, brent_long, gold_long, vix_long, tlt_long)


# ─── Nivel global ───────────────────────────────────────────────────────────
def calcular_nivel():
    razones, nivel = [], "ELEVATED"
    if brent and abs(brent["variacion_pct"]) >= 5:
        nivel = "HIGH"
        razones.append(f"Brent {brent['variacion_pct']:+.1f}%")
    if wti and brent:
        sp = wti["precio"] - brent["precio"]
        if sp > 3 or sp < -10:
            if nivel == "ELEVATED":
                nivel = "HIGH"
            razones.append(f"spread {sp:+.1f}")
    if not resumen_cp.empty:
        peor = resumen_cp.dropna(subset=["z_score"]).sort_values("z_score")
        if not peor.empty:
            f = peor.iloc[0]
            if f["z_score"] <= -2.0 and f.get("lag_dias", 999) <= 10:
                nivel = "HIGH"
                razones.append(f"{f['portname']} z={f['z_score']:.1f}")
    if score_data["score"] <= -0.4 and score_data["n_cuentas"] >= 3:
        if nivel == "ELEVATED":
            nivel = "HIGH"
        razones.append(f"sent {score_data['score']:+.2f}")
    if not df_rss.empty:
        atq = df_rss[df_rss["es_ataque_refineria"]]
        if not atq.empty:
            ult = atq["fecha"].max()
            if pd.notna(ult):
                horas = (datetime.now(timezone.utc) - ult).total_seconds() / 3600
                if horas <= 72:
                    nivel = "CRITICAL"
                    razones.append(f"refinería h-{int(horas)}")
    if ovx and ovx["precio"] > 50:
        if nivel == "ELEVATED":
            nivel = "HIGH"
        razones.append(f"OVX {ovx['precio']:.0f}")
    return nivel, " · ".join(razones) if razones else "monitoring"


nivel, sub = calcular_nivel()
app_header(nivel, sub)

# Descripción global del dashboard
st.markdown(
    '<div class="section-desc" style="margin-top:8px;">'
    'Tablero de seguimiento del conflicto <em>Irán ↔ EE.UU. / Israel</em> desde el ángulo de '
    'mercados de energía. Combina cotizaciones de <em>yfinance</em> (delay ~15-20 min, '
    'free tier), tránsitos de tanqueros de <em>IMF PortWatch</em> (lag semanal), sentiment '
    'OSINT desde <em>Bluesky</em> y noticias de <em>GDELT 2.0</em> y feeds RSS. El indicador '
    'de nivel global combina seis señales: spike Brent, dislocación WTI-Brent, disrupción '
    'de chokepoints, sentiment, ataques a refinerías y vol del crudo (^OVX). '
    '<em>Para ver real-time hay que pagar fuente paga; con yfinance gratis hay un mínimo '
    'estructural de ~15 min de delay sobre el último tick del mercado.</em>'
    '</div>',
    unsafe_allow_html=True,
)


# ═══ RESUMEN IA ══════════════════════════════════════════════════════════════
def _payload_para_resumen() -> dict:
    """Empaqueta los datos clave en estructura hashable para el cache."""
    cps_payload = []
    if not resumen_cp.empty:
        for _, f in resumen_cp.iterrows():
            cps_payload.append({
                "nombre": str(f["portname"]),
                "actual": float(f["actual"]) if pd.notna(f["actual"]) else 0.0,
                "baseline": float(f["baseline"]) if pd.notna(f["baseline"]) else 0.0,
                "desvio_pct": float(f["desvio_pct"]) if pd.notna(f["desvio_pct"]) else None,
                "z_score": float(f["z_score"]) if pd.notna(f["z_score"]) else None,
                "lag_dias": int(f.get("lag_dias", 0)),
            })
    eventos_recientes = []
    if not df_rss.empty:
        for _, r in df_rss.head(8).iterrows():
            eventos_recientes.append({
                "fuente": str(r["fuente"])[:18],
                "titulo": str(r["titulo"])[:160],
            })
    if not df_gdelt.empty:
        for _, r in df_gdelt.head(4).iterrows():
            eventos_recientes.append({
                "fuente": "GDELT",
                "titulo": str(r["titulo"])[:160],
            })
    ataques_72h = 0
    if not df_rss.empty:
        atq = df_rss[
            df_rss["es_ataque_refineria"]
            & (df_rss["fecha"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=72))
        ]
        ataques_72h = int(len(atq))

    hsi_actual = None
    if not hsi.empty:
        s = hsi["HSI"].dropna()
        if not s.empty:
            hsi_actual = float(s.iloc[-1])

    return {
        "nivel": nivel,
        "razones": sub,
        "brent": {"precio": brent["precio"], "variacion_pct": brent["variacion_pct"]} if brent else None,
        "wti": {"precio": wti["precio"], "variacion_pct": wti["variacion_pct"]} if wti else None,
        "spread": (wti["precio"] - brent["precio"]) if (wti and brent) else None,
        "ovx": {"precio": ovx["precio"], "variacion_pct": ovx["variacion_pct"]} if ovx else None,
        "hsi": hsi_actual,
        "chokepoints": cps_payload,
        "sentiment_score": float(score_data.get("score", 0)),
        "sentiment_cuentas": int(score_data.get("n_cuentas", 0)),
        "sentiment_posts": int(score_data.get("n_posts", 0)),
        "ataques_72h": ataques_72h,
        "eventos_recientes": eventos_recientes,
    }


# Streamlit cache_data necesita parámetros hashables. Convertimos a tupla.
def _to_hashable(d):
    if isinstance(d, dict):
        return tuple(sorted((k, _to_hashable(v)) for k, v in d.items()))
    if isinstance(d, list):
        return tuple(_to_hashable(x) for x in d)
    return d


with st.spinner("Generando resumen…"):
    payload = _payload_para_resumen()
    texto_brief, modelo_brief = generar_resumen(payload, SESSION_KEY)
brief(texto_brief, modelo_brief)
btn_col1, btn_col2, _ = st.columns([1, 1, 4])
if btn_col1.button("↻ Refrescar datos", key="btn_refrescar_datos",
                    help="Limpia cache de yfinance, PortWatch, RSS, GDELT y Bluesky"):
    st.cache_data.clear()
    st.rerun()
if btn_col2.button("↻ Regenerar IA", key="btn_regen_ai",
                    help="Fuerza nueva llamada a Claude (resumen + sentiment)"):
    st.session_state.ai_session_key = int(datetime.now(timezone.utc).timestamp())
    st.rerun()


# ═══ KPI STRIP ═══════════════════════════════════════════════════════════════
k = st.columns([1.4, 1.4, 1, 1, 1, 1.4])

with k[0]:
    if brent:
        estado = "warn" if abs(brent["variacion_pct"]) >= 3 else "normal"
        st.markdown(kpi(
            "Brent ICE", f"${brent['precio']:.2f}",
            f"{brent['variacion_pct']:+.2f}%", "USD/bbl",
            estado=estado, tamano="xl",
        ), unsafe_allow_html=True)
    else:
        st.markdown(kpi("Brent ICE", "s/d", None, "yfinance", tamano="xl"),
                    unsafe_allow_html=True)

with k[1]:
    if wti:
        st.markdown(kpi(
            "WTI NYMEX", f"${wti['precio']:.2f}",
            f"{wti['variacion_pct']:+.2f}%", "USD/bbl", tamano="xl",
        ), unsafe_allow_html=True)
    else:
        st.markdown(kpi("WTI NYMEX", "s/d", None, "yfinance", tamano="xl"),
                    unsafe_allow_html=True)

with k[2]:
    if wti and brent:
        sp = wti["precio"] - brent["precio"]
        prev = wti["previo"] - brent["previo"] if (wti["previo"] and brent["previo"]) else 0
        ds = sp - prev
        estado = "warn" if (sp > 3 or sp < -10) else "normal"
        st.markdown(kpi(
            "WTI–Brent", f"${sp:+.2f}", f"{ds:+.2f}", "diferencial",
            estado=estado,
        ), unsafe_allow_html=True)

with k[3]:
    h = resumen_cp[resumen_cp["portid"] == "chokepoint6"] if not resumen_cp.empty else pd.DataFrame()
    if not h.empty:
        f = h.iloc[0]
        z = f["z_score"]
        estado = "alert" if (pd.notna(z) and z <= -2.0) else "warn" if (pd.notna(z) and z <= -1.0) else "normal"
        desvio = f["desvio_pct"] if pd.notna(f["desvio_pct"]) else 0
        st.markdown(kpi(
            "Hormuz tank/d", f"{f['actual']:.0f}",
            f"{desvio:+.0f}%", f"PortWatch · lag {int(f.get('lag_dias',0))}d",
            estado=estado,
        ), unsafe_allow_html=True)
    else:
        st.markdown(kpi("Hormuz tank/d", "s/d"), unsafe_allow_html=True)

with k[4]:
    ult_atq_text = "—"
    src_text = "RSS"
    estado = "normal"
    if not df_rss.empty:
        atq = df_rss[df_rss["es_ataque_refineria"]]
        if not atq.empty:
            ult_row = atq.sort_values("fecha", ascending=False).iloc[0]
            ult_fecha = ult_row["fecha"]
            if pd.notna(ult_fecha):
                ult_atq_text = hace_cuanto(ult_fecha)
                horas = (datetime.now(timezone.utc) - ult_fecha).total_seconds() / 3600
                if horas <= 24:
                    estado = "alert"
                elif horas <= 72:
                    estado = "warn"
                src_text = ult_row["fuente"][:20]
    st.markdown(kpi(
        "Últ. refinería", ult_atq_text, None, src_text, estado=estado,
    ), unsafe_allow_html=True)

with k[5]:
    if score_data["n_posts"] > 0:
        s = score_data["score"]
        estado = "alert" if s <= -0.4 else "warn" if s <= -0.2 else "normal"
        modelo_short = "claude" if sentiment_modelo.startswith("claude") else "vader"
        st.markdown(kpi(
            "OSINT 24h", f"{s:+.1f}", None,
            f"{score_data['n_cuentas']} cuentas · {score_data['n_posts']} posts · {modelo_short}",
            estado=estado,
        ), unsafe_allow_html=True)
    else:
        st.markdown(kpi("OSINT 24h", "s/d", None, "Bluesky"), unsafe_allow_html=True)


# ═══ MERCADOS ════════════════════════════════════════════════════════════════
st.markdown('<h2>Mercados</h2>', unsafe_allow_html=True)
section_desc(
    "<em>Brent</em> es el benchmark global del crudo seaborne; <em>WTI</em> el referente "
    "norteamericano. El <em>spread WTI-Brent</em> indica la prima de arbitraje: en "
    "disrupciones físicas del Golfo, Brent sube más que WTI y el spread se vuelve más "
    "negativo. El <em>HSI (Hormuz Stress Index)</em> compone z-scores rolling de OVX, "
    "VIX, TLT, Brent y oro — valores >+1.5 indican que el mercado está pricing un evento."
)

m_col_l, m_col_r = st.columns([2, 1])

with m_col_l:
    if not brent_h60.empty and not wti_h60.empty:
        merged = brent_h60.merge(wti_h60, on="fecha", suffixes=("_brent", "_wti"))
        merged["spread"] = merged["cierre_wti"] - merged["cierre_brent"]
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.72, 0.28], vertical_spacing=0.04,
        )
        fig.add_trace(go.Scatter(
            x=merged["fecha"], y=merged["cierre_brent"],
            name="Brent", line=dict(color=PALETA["ambar"], width=2),
            hovertemplate="Brent<br>%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=merged["fecha"], y=merged["cierre_wti"],
            name="WTI", line=dict(color=PALETA["azul"], width=2),
            hovertemplate="WTI<br>%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=merged["fecha"], y=merged["spread"],
            name="Spread", line=dict(color=PALETA["violeta"], width=1.5),
            fill="tozeroy", fillcolor="rgba(139,111,184,0.12)",
            showlegend=False,
            hovertemplate="Spread<br>%{x|%Y-%m-%d}<br>$%{y:+.2f}<extra></extra>",
        ), row=2, col=1)
        fig.add_hline(y=0, line=dict(color=PALETA["borde"], width=0.8), row=2, col=1)
        fig.update_yaxes(title_text="USD/bbl", row=1, col=1, gridcolor="#1A2129", title_font=dict(size=10, color=PALETA["texto_3"]))
        fig.update_yaxes(title_text="Spread", row=2, col=1, gridcolor="#1A2129", title_font=dict(size=10, color=PALETA["texto_3"]))
        fig.update_xaxes(gridcolor="#1A2129", row=1, col=1)
        fig.update_xaxes(gridcolor="#1A2129", row=2, col=1)
        fig.update_layout(
            height=340, hovermode="x unified",
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
            font=dict(family="Inter", color=PALETA["texto_2"], size=11),
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                        bgcolor="rgba(0,0,0,0)", font=dict(color=PALETA["texto_2"], size=10)),
            hoverlabel=dict(bgcolor=PALETA["fondo_elev"], bordercolor=PALETA["borde"],
                            font=dict(family="JetBrains Mono", size=10, color=PALETA["texto"])),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            '<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;">'
            'Brent y WTI 60d · spread inferior · yfinance</div>',
            unsafe_allow_html=True,
        )

with m_col_r:
    if not hsi.empty:
        hsi_recent = hsi.tail(180).copy()
        colores = [
            PALETA["rojo"] if v >= 1.5 else PALETA["naranja"] if v >= 0.5
            else PALETA["azul"] if v >= -0.5 else PALETA["verde"]
            for v in hsi_recent["HSI"].fillna(0)
        ]
        fig_h = go.Figure()
        fig_h.add_trace(go.Bar(
            x=hsi_recent["fecha"], y=hsi_recent["HSI"],
            marker_color=colores,
            hovertemplate="%{x|%Y-%m-%d}<br>HSI: %{y:+.2f}<extra></extra>",
        ))
        fig_h.add_hline(y=1.5, line=dict(color=PALETA["rojo"], width=0.8, dash="dash"))
        fig_h.add_hline(y=-1.5, line=dict(color=PALETA["verde"], width=0.8, dash="dash"))
        fig_h.add_hline(y=0, line=dict(color=PALETA["borde"], width=0.5))
        fig_h.update_layout(
            height=340, hovermode="x",
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
            font=dict(family="Inter", color=PALETA["texto_2"], size=10),
            margin=dict(l=8, r=8, t=20, b=10),
            xaxis=dict(gridcolor="#1A2129"),
            yaxis=dict(gridcolor="#1A2129", title="HSI", title_font=dict(size=10, color=PALETA["texto_3"])),
            hoverlabel=dict(bgcolor=PALETA["fondo_elev"], bordercolor=PALETA["borde"],
                            font=dict(family="JetBrains Mono", size=10, color=PALETA["texto"])),
        )
        st.plotly_chart(fig_h, use_container_width=True, config={"displayModeBar": False})
        ult = hsi["HSI"].dropna().iloc[-1] if not hsi["HSI"].dropna().empty else None
        if ult is not None:
            estado_text = "STRESS" if ult >= 1.5 else "ELEVADO" if ult >= 0.5 else "NORMAL" if ult >= -0.5 else "CALMO"
            color = "#D97A7A" if ult >= 1.5 else "#C9A227" if ult >= 0.5 else "#A0A8B4" if ult >= -0.5 else "#7FB893"
            st.markdown(
                f'<div style="font-size:11px;color:#6B7280;font-family:JetBrains Mono;">'
                f'HSI <span style="color:{color}">{ult:+.2f}</span> · {estado_text} · 5-comp</div>',
                unsafe_allow_html=True,
            )


# ═══ CHOKEPOINTS ═════════════════════════════════════════════════════════════
st.markdown('<h2>Chokepoints</h2>', unsafe_allow_html=True)
section_desc(
    "Tránsito diario de tanqueros por los tres puntos críticos del flujo global de crudo: "
    "<em>Hormuz</em> (~30% del crudo marítimo mundial), <em>Suez</em> (Mediterráneo–Mar Rojo) "
    "y <em>Bab el-Mandeb</em> (entrada sur al Mar Rojo). El <em>baseline</em> usa la mediana "
    "de los mismos días de semana de los últimos 90 días (robusto a outliers via MAD). "
    "Un z-score ≤ -2 marca disrupción; los datos de PortWatch llegan con ~5-7 días de lag."
)

if df_cp.empty:
    st.markdown(
        '<div style="color:#6B7280;font-size:11px;">PortWatch sin datos.</div>',
        unsafe_allow_html=True,
    )
else:
    ult_fecha_cp = df_cp["fecha"].max()
    lag_cp = int((pd.Timestamp.now(tz="UTC").normalize() - ult_fecha_cp.normalize()).days)

    c_cols = st.columns(len(cps_cfg))
    for i, c in enumerate(cps_cfg):
        fila = resumen_cp[resumen_cp["portid"] == c["portid"]]
        if fila.empty:
            continue
        f = fila.iloc[0]
        z = f["z_score"]
        estado = "alert" if (pd.notna(z) and z <= -2.0) else "warn" if (pd.notna(z) and z <= -1.0) else "normal"
        desvio = f["desvio_pct"] if pd.notna(f["desvio_pct"]) else 0
        z_text = f"{z:.2f}" if pd.notna(z) else "—"
        with c_cols[i]:
            st.markdown(kpi(
                c["nombre_corto"], f"{f['actual']:.0f}",
                f"{desvio:+.0f}% vs base", f"z={z_text} · MAD robust",
                estado=estado,
            ), unsafe_allow_html=True)

    fig_cp = go.Figure()
    for c in cps_cfg:
        g = df_cp[df_cp["portid"] == c["portid"]].sort_values("fecha")
        if g.empty:
            continue
        g["ma7"] = g["n_tanker"].rolling(7, min_periods=1).mean()
        fig_cp.add_trace(go.Scatter(
            x=g["fecha"], y=g["ma7"],
            name=c["nombre_corto"], mode="lines",
            line=dict(width=2, color=c["color"]),
            hovertemplate=safe(c["nombre_corto"]) + "<br>%{x|%Y-%m-%d}<br>%{y:.0f}<extra></extra>",
        ))
    aplicar(fig_cp, height=300, hovermode="x unified",
            yaxis_title="Tanqueros (MA7)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                        bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
            margin=dict(l=8, r=8, t=20, b=10))
    st.plotly_chart(fig_cp, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        f'<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;">'
        f'IMF PortWatch · último dato {ult_fecha_cp.strftime("%Y-%m-%d")} (lag {lag_cp}d) · '
        f'baseline = mediana misma DOW últimos 90d</div>',
        unsafe_allow_html=True,
    )


# ═══ RESERVAS ESTRATÉGICAS ═══════════════════════════════════════════════════
st.markdown('<h2>Reservas estratégicas</h2>', unsafe_allow_html=True)
section_desc(
    "Reservas estratégicas (SPR gobierno-controladas) por región, en millones de barriles. "
    "Línea punteada vertical = inicio del conflicto (13-abr-2024). Cada panel con su propia "
    "escala. <strong>Días de cobertura</strong> = SPR / importaciones netas de crudo (estándar "
    "IEA, lo que mide cuánto aguanta cada país sin imports). Colores: rojo &lt;30d · "
    "naranja &lt;60d · ámbar &lt;90d (mínimo IEA) · verde ≥90d. "
    "<em>USA</em>: EIA WCSSTUS1 live. <em>Resto</em>: EIA Today In Energy + IEA OMR; "
    "China = total bajo control estatal (govt SPR + comercial vía SOEs)."
)

cfg_res = cargar("reservas.yaml")
fecha_conflicto = cfg_res.get("fecha_inicio_conflicto", "2024-04-13")
series = series_historicas(cfg_res, desde=fecha_conflicto)
df_res = snapshot_global(cfg_res, series=series)
fecha_jodi = ultima_fecha_jodi(series)

COLOR_PAIS = {
    "USA": PALETA["ambar"],
    "China": PALETA["rojo"],
    "Japón": PALETA["azul"],
    "OECD Europa": PALETA["violeta"],
}

col_evo, col_snap = st.columns([2.2, 1])

with col_evo:
    if series:
        # Orden fijo top→bottom, left→right en grilla 2x2
        orden_paises = ["China", "USA", "OECD Europa", "Japón"]
        paises_disp = [p for p in orden_paises if p in series and not series[p].empty]
        if paises_disp:
            try:
                x_conflicto = pd.Timestamp(fecha_conflicto, tz="UTC")
            except Exception:
                x_conflicto = None

            # Lookup rápido por país para consumo / días cobertura
            res_lookup = {r["pais"]: r for _, r in df_res.iterrows()} if not df_res.empty else {}
            # Subtítulos con: SPR actual, % cambio vs conflicto, consumo, días cover
            titulos = []
            for pais in paises_disp:
                df_s = series[pais]
                idx_base = (df_s["fecha"] - x_conflicto).abs().idxmin() if x_conflicto is not None else 0
                val_base = float(df_s.loc[idx_base, "mbbl"])
                val_ult = float(df_s.iloc[-1]["mbbl"])
                delta_pct = (val_ult - val_base) / val_base * 100 if val_base else 0
                color_delta = PALETA["verde"] if delta_pct >= 0 else PALETA["rojo"]
                info = res_lookup.get(pais, {})
                consumo = info.get("consumo_diario_mbbl", 0)
                dias = info.get("dias_cobertura")
                # Días de cobertura con color por umbral IEA (90d = obligación)
                if dias is None or pd.isna(dias):
                    cover_html = ""
                else:
                    if dias < 30:
                        c_d = PALETA["rojo"]
                    elif dias < 60:
                        c_d = PALETA["naranja"]
                    elif dias < 90:
                        c_d = PALETA["ambar"]
                    else:
                        c_d = PALETA["verde"]
                    c_meta = PALETA["texto_3"]
                    cover_html = (
                        f"<br><span style='color:{c_meta};font-size:10px;font-weight:normal;'>"
                        f"consumo {consumo:.1f} Mbbl/d · "
                        f"<span style='color:{c_d};font-weight:600;'>{dias:.0f} días cobertura</span>"
                        f"</span>"
                    )
                titulos.append(
                    f"<b>{pais}</b> · {val_ult:.0f} Mbbl "
                    f"<span style='color:{color_delta}'>({delta_pct:+.1f}%)</span>"
                    f"{cover_html}"
                )

            fig_grid = make_subplots(
                rows=2, cols=2,
                subplot_titles=titulos,
                horizontal_spacing=0.08, vertical_spacing=0.24,
            )

            for i, pais in enumerate(paises_disp):
                row = i // 2 + 1
                col = i % 2 + 1
                df_s = series[pais]
                es_continuo = pais == "USA" or len(df_s) > 12
                color = COLOR_PAIS.get(pais, PALETA["texto"])
                fig_grid.add_trace(
                    go.Scatter(
                        x=df_s["fecha"], y=df_s["mbbl"],
                        mode="lines" if es_continuo else "lines+markers",
                        line=dict(width=2, color=color),
                        marker=dict(size=5) if not es_continuo else dict(size=0),
                        fill="tozeroy",
                        fillcolor=f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.10)",
                        hovertemplate=f"<b>{safe(pais)}</b><br>%{{x|%Y-%m}}<br>%{{y:.0f}} Mbbl<extra></extra>",
                        showlegend=False,
                    ),
                    row=row, col=col,
                )
                # Línea vertical inicio conflicto
                if x_conflicto is not None:
                    fig_grid.add_vline(
                        x=x_conflicto, line_width=1, line_dash="dot",
                        line_color=PALETA["texto_3"],
                        row=row, col=col,
                    )
                # Y-axis ajustado para que no arranque en 0 (resalta variaciones)
                ymin = df_s["mbbl"].min() * 0.93
                ymax = df_s["mbbl"].max() * 1.05
                fig_grid.update_yaxes(range=[ymin, ymax], row=row, col=col)

            aplicar(
                fig_grid, height=460,
                margin=dict(l=8, r=8, t=50, b=10),
                showlegend=False,
            )
            # Subplot titles más chicos
            for ann in fig_grid["layout"]["annotations"]:
                ann["font"] = dict(size=11, color=PALETA["texto"])
            st.plotly_chart(fig_grid, use_container_width=True, config={"displayModeBar": False})
            st.markdown(
                '<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;">'
                'Cada eje Y autoescala; el % al lado del nombre = cambio vs 13-abr-2024 (inicio conflicto).</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="color:#6B7280;font-size:11px;">Sin datos de series históricas.</div>',
                unsafe_allow_html=True,
            )

with col_snap:
    st.markdown(
        '<div style="font-size:11px;color:#A0A8B4;margin-bottom:4px;">'
        'Snapshot actual</div>',
        unsafe_allow_html=True,
    )
    if not df_res.empty:
        df_res_sorted = df_res.sort_values("mbbl", ascending=True)
        colores = [COLOR_PAIS.get(p, PALETA["texto"]) for p in df_res_sorted["pais"]]
        textos = [f"{m:.0f}" for m in df_res_sorted["mbbl"]]
        fig_snap = go.Figure(go.Bar(
            y=df_res_sorted["pais"],
            x=df_res_sorted["mbbl"],
            orientation="h",
            marker=dict(color=colores),
            text=textos,
            textposition="outside",
            textfont=dict(color=PALETA["texto_2"], size=10),
            hovertemplate="<b>%{y}</b><br>%{x:.0f} Mbbl<extra></extra>",
        ))
        aplicar(
            fig_snap, height=340,
            xaxis_title="Mbbl · escala log",
            xaxis_type="log",
            margin=dict(l=8, r=60, t=20, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_snap, use_container_width=True, config={"displayModeBar": False})

if not df_res.empty:
    fuente_url = cfg_res.get("url_fuente", "")
    fecha_snap = cfg_res.get("fecha_snapshot", "")
    fuente_link = (
        f'<a href="{safe(fuente_url)}" target="_blank">EIA Today In Energy + IEA OMR</a>'
        if fuente_url else "EIA Today In Energy + IEA OMR"
    )
    fecha_label = safe(fecha_jodi) if fecha_jodi else safe(fecha_snap)
    st.markdown(
        f'<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;margin-top:4px;">'
        f'USA: EIA WCSSTUS1 live (semanal). Resto: {fuente_link} · última referencia <strong>{fecha_label}</strong>. '
        f'Editá <code>config/reservas.yaml</code> cuando salgan nuevos releases o EIA publique nuevo análisis.</div>',
        unsafe_allow_html=True,
    )


# ═══ INVENTARIOS DE GAS / GNL ════════════════════════════════════════════════
st.markdown('<h2>Inventarios de gas / GNL</h2>', unsafe_allow_html=True)
section_desc(
    "Reservas de gas natural en almacenamiento por región, en BCM (billion cubic meters). "
    "A diferencia del SPR de crudo, el storage de gas es <strong>altamente estacional</strong> "
    "(inyección verano, draw invierno). Línea punteada vertical = inicio del conflicto. "
    "<strong>Días de cobertura</strong> = inventario / consumo diario promedio (referencial — "
    "en invierno el consumo puede 3-4x el promedio). Colores: rojo &lt;20d · naranja &lt;40d · "
    "ámbar &lt;60d · verde ≥60d. <em>USA</em>: EIA NW2 live semanal. <em>EU</em>: AGSI+ (GIE) "
    "puntos curados. <em>Japón</em>: METI weekly LNG en utilities. <em>China</em>: NDRC/IEA estimates. "
    "Qatar (en el Pérsico) es el mayor exportador de GNL — Hormuz disruption afecta directamente."
)

cfg_gas = cargar("gas.yaml")
fecha_conflicto_gas = cfg_gas.get("fecha_inicio_conflicto", "2024-04-13")
series_gas = series_historicas_gas(cfg_gas, desde=fecha_conflicto_gas)
df_gas = snapshot_global_gas(cfg_gas, series=series_gas)
fecha_gas_ult = ultima_fecha_gas(series_gas)

COLOR_GAS = {
    "USA": PALETA["ambar"],
    "EU": PALETA["violeta"],
    "China": PALETA["rojo"],
    "Japón": PALETA["azul"],
}

col_gas_evo, col_gas_snap = st.columns([2.2, 1])

with col_gas_evo:
    if series_gas:
        orden_paises_gas = ["USA", "EU", "China", "Japón"]
        paises_disp_g = [p for p in orden_paises_gas if p in series_gas and not series_gas[p].empty]
        if paises_disp_g:
            try:
                x_conflicto_g = pd.Timestamp(fecha_conflicto_gas, tz="UTC")
            except Exception:
                x_conflicto_g = None

            gas_lookup = {r["pais"]: r for _, r in df_gas.iterrows()} if not df_gas.empty else {}
            titulos_g = []
            for pais in paises_disp_g:
                df_s = series_gas[pais]
                idx_base = (df_s["fecha"] - x_conflicto_g).abs().idxmin() if x_conflicto_g is not None else 0
                val_base = float(df_s.loc[idx_base, "bcm"])
                val_ult = float(df_s.iloc[-1]["bcm"])
                delta_pct = (val_ult - val_base) / val_base * 100 if val_base else 0
                color_delta = PALETA["verde"] if delta_pct >= 0 else PALETA["rojo"]
                info = gas_lookup.get(pais, {})
                consumo = info.get("consumo_diario_bcm", 0)
                dias = info.get("dias_cobertura")
                pct_cap = info.get("pct_capacidad")
                if dias is None or pd.isna(dias):
                    cover_html = ""
                else:
                    if dias < 20:
                        c_d = PALETA["rojo"]
                    elif dias < 40:
                        c_d = PALETA["naranja"]
                    elif dias < 60:
                        c_d = PALETA["ambar"]
                    else:
                        c_d = PALETA["verde"]
                    c_meta = PALETA["texto_3"]
                    pct_str = f" · {pct_cap:.0f}% cap" if pct_cap and not pd.isna(pct_cap) else ""
                    cover_html = (
                        f"<br><span style='color:{c_meta};font-size:10px;font-weight:normal;'>"
                        f"consumo {consumo:.2f} BCM/d · "
                        f"<span style='color:{c_d};font-weight:600;'>{dias:.0f} días cobertura</span>"
                        f"{pct_str}</span>"
                    )
                titulos_g.append(
                    f"<b>{pais}</b> · {val_ult:.1f} BCM "
                    f"<span style='color:{color_delta}'>({delta_pct:+.1f}%)</span>"
                    f"{cover_html}"
                )

            fig_g = make_subplots(
                rows=2, cols=2,
                subplot_titles=titulos_g,
                horizontal_spacing=0.08, vertical_spacing=0.24,
            )
            for i, pais in enumerate(paises_disp_g):
                row = i // 2 + 1
                col = i % 2 + 1
                df_s = series_gas[pais]
                es_continuo = pais == "USA" or len(df_s) > 12
                color = COLOR_GAS.get(pais, PALETA["texto"])
                fig_g.add_trace(
                    go.Scatter(
                        x=df_s["fecha"], y=df_s["bcm"],
                        mode="lines" if es_continuo else "lines+markers",
                        line=dict(width=2, color=color),
                        marker=dict(size=5) if not es_continuo else dict(size=0),
                        fill="tozeroy",
                        fillcolor=f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.10)",
                        hovertemplate=f"<b>{safe(pais)}</b><br>%{{x|%Y-%m}}<br>%{{y:.1f}} BCM<extra></extra>",
                        showlegend=False,
                    ),
                    row=row, col=col,
                )
                if x_conflicto_g is not None:
                    fig_g.add_vline(
                        x=x_conflicto_g, line_width=1, line_dash="dot",
                        line_color=PALETA["texto_3"],
                        row=row, col=col,
                    )
                ymin = df_s["bcm"].min() * 0.85
                ymax = df_s["bcm"].max() * 1.10
                fig_g.update_yaxes(range=[ymin, ymax], row=row, col=col)

            aplicar(
                fig_g, height=460,
                margin=dict(l=8, r=8, t=50, b=10),
                showlegend=False,
            )
            for ann in fig_g["layout"]["annotations"]:
                ann["font"] = dict(size=11, color=PALETA["texto"])
            st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})
            st.markdown(
                '<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;">'
                'BCM = billion cubic meters · 1 BCM = 35.3 Bcf ≈ 11 TWh · USA semanal (EIA), resto trimestral (curado)</div>',
                unsafe_allow_html=True,
            )

with col_gas_snap:
    st.markdown(
        '<div style="font-size:11px;color:#A0A8B4;margin-bottom:4px;">Snapshot actual (BCM)</div>',
        unsafe_allow_html=True,
    )
    if not df_gas.empty:
        df_gas_sorted = df_gas.sort_values("bcm", ascending=True)
        colores_g = [COLOR_GAS.get(p, PALETA["texto"]) for p in df_gas_sorted["pais"]]
        textos_g = [f"{b:.1f}" for b in df_gas_sorted["bcm"]]
        fig_gsnap = go.Figure(go.Bar(
            y=df_gas_sorted["pais"],
            x=df_gas_sorted["bcm"],
            orientation="h",
            marker=dict(color=colores_g),
            text=textos_g,
            textposition="outside",
            textfont=dict(color=PALETA["texto_2"], size=10),
            hovertemplate="<b>%{y}</b><br>%{x:.1f} BCM<extra></extra>",
        ))
        aplicar(
            fig_gsnap, height=460,
            xaxis_title="BCM · escala log",
            xaxis_type="log",
            margin=dict(l=8, r=60, t=20, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_gsnap, use_container_width=True, config={"displayModeBar": False})

if not df_gas.empty:
    fecha_label_g = safe(fecha_gas_ult) if fecha_gas_ult else safe(cfg_gas.get("fecha_snapshot", ""))
    st.markdown(
        f'<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;margin-top:4px;">'
        f'USA: EIA NW2 live (semanal). EU/Japón/China: AGSI+ (GIE) + METI + IEA · última referencia <strong>{fecha_label_g}</strong>. '
        f'Qatar (Pérsico) = ~20% LNG mundial — Hormuz disruption afecta directo a importadores asiáticos.</div>',
        unsafe_allow_html=True,
    )


# ═══ INTELIGENCIA ABIERTA ════════════════════════════════════════════════════
st.markdown('<h2>Inteligencia abierta</h2>', unsafe_allow_html=True)
_modelo_sent_desc = (
    "<em>Claude Haiku 4.5</em> clasificando cada post sobre el eje "
    "<strong>geopolítico-energético</strong> (escalada / desescalada / "
    "tensión-mercado / disrupción-oferta / etc.). NO mide tono emocional: "
    "\"Trump cancela negociaciones\" suena neutro pero se clasifica como "
    "escalada negativa."
    if sentiment_modelo.startswith("claude") else
    "<em>VADER</em> (lexicón emocional inglés) — mide si el texto suena "
    "positivo o negativo, NO el impacto geopolítico. Para usar el modelo "
    "geopolítico real, exportá <code>ANTHROPIC_API_KEY</code> y reiniciá."
)
section_desc(
    "El <em>tape</em> de la izquierda mezcla titulares de RSS (BBC, Al Jazeera, Guardian, "
    "Times of Israel, Tehran Times) y artículos de <em>GDELT 2.0</em> filtrados por keywords "
    "de conflicto.<br><br>"
    "A la derecha, el <em>índice de sentiment OSINT</em>. Pipeline: "
    "<strong>(1)</strong> se descargan los últimos posts de las cuentas en "
    "<code>cuentas_bluesky.yaml</code>; "
    "<strong>(2)</strong> se filtran por keywords de geopolítica y mercado de energía "
    f"({n_posts_relevantes}/{n_posts_total} posts pasaron el filtro); "
    f"<strong>(3)</strong> a cada post se le asigna un score ∈ <strong>[-1, +1]</strong> "
    f"con {_modelo_sent_desc} "
    "<strong>(4)</strong> agregación en dos pasos para evitar que una cuenta verbosa "
    "domine: primero se promedia el score <em>por cuenta</em>, después se hace un "
    "promedio ponderado entre cuentas usando el campo <code>peso</code> "
    "(confiabilidad ∈ [0,1]). Lecturas: <strong>|score| ≤ 0.15</strong> neutro, "
    "<strong>≤ -0.30</strong> bajista, <strong>≤ -0.50</strong> alarma, "
    "<strong>≥ 0.30</strong> alcista. Ventana: 24h. "
    f"<em>Cache por sesión: 1 llamada por F5/regenerar.</em>"
)

i_col_l, i_col_r = st.columns([1.4, 1])

with i_col_l:
    st.markdown(
        '<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;'
        'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">Tape de eventos</div>',
        unsafe_allow_html=True,
    )
    eventos = []
    if not df_rss.empty:
        for _, r in df_rss.head(15).iterrows():
            f = r["fecha"]
            if pd.notna(f):
                eventos.append({
                    "fecha": f, "fuente": r["fuente"],
                    "titulo": r["titulo"], "url": r.get("url", ""),
                    "alerta": bool(r.get("es_ataque_refineria")),
                })
    if not df_gdelt.empty:
        for _, r in df_gdelt.head(10).iterrows():
            f = r["fecha"]
            if pd.notna(f):
                eventos.append({
                    "fecha": f, "fuente": "GDELT",
                    "titulo": r["titulo"], "url": r.get("url", ""),
                    "alerta": "refiner" in (r["titulo"] or "").lower(),
                })
    eventos = sorted(eventos, key=lambda x: x["fecha"], reverse=True)[:25]
    rows = []
    for e in eventos:
        clase = " alerta" if e["alerta"] else ""
        ts_str = e["fecha"].strftime("%d/%m %H:%M")
        src = safe((e["fuente"] or "")[:8].lower())
        title = safe((e["titulo"] or "")[:120])
        url = safe(e["url"])
        link = f'<a href="{url}" target="_blank">{title}</a>' if url else title
        rows.append(
            f'<div class="tape-row{clase}">'
            f'<span class="ts">{ts_str}</span>'
            f'<span class="src">{src}</span>{link}</div>'
        )
    st.markdown(
        f'<div class="tape">{"".join(rows) or "<div class=tape-row>Sin eventos.</div>"}</div>',
        unsafe_allow_html=True,
    )

with i_col_r:
    st.markdown(
        '<div style="font-size:10px;color:#6B7280;font-family:JetBrains Mono;'
        'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">Sentiment 24h</div>',
        unsafe_allow_html=True,
    )
    if score_data["n_posts"] > 0:
        s = score_data["score"]
        bar_color = (
            PALETA["rojo"] if s < -0.3
            else PALETA["verde"] if s > 0.3
            else PALETA["azul"]
        )
        fig_g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=float(s),
            number={"valueformat": "+.2f", "font": {"size": 32, "color": PALETA["texto"]}},
            gauge={
                "axis": {"range": [-1, 1], "tickcolor": PALETA["texto_3"],
                         "tickfont": {"color": PALETA["texto_3"], "size": 9}},
                "bar": {"color": bar_color, "thickness": 0.22},
                "bgcolor": PALETA["fondo_app"],
                "borderwidth": 0,
                "steps": [
                    {"range": [-1, -0.5], "color": "rgba(179,58,58,0.20)"},
                    {"range": [-0.5, -0.15], "color": "rgba(217,122,44,0.13)"},
                    {"range": [-0.15, 0.15], "color": "rgba(26,33,41,1.0)"},
                    {"range": [0.15, 0.5], "color": "rgba(63,143,92,0.13)"},
                    {"range": [0.5, 1], "color": "rgba(63,143,92,0.27)"},
                ],
                "threshold": {
                    "line": {"color": PALETA["texto"], "width": 2},
                    "thickness": 0.85, "value": float(s),
                },
            },
        ))
        fig_g.update_layout(
            height=200, margin=dict(l=20, r=20, t=10, b=0),
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"],
        )
        st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})

        # Top extremos compactos
        df_v = df_bsky[
            df_bsky["creado_en"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)
        ].dropna(subset=["score"])
        if not df_v.empty:
            tops = pd.concat([
                df_v.nsmallest(2, "score"),
                df_v.nlargest(2, "score"),
            ]).sort_values("score")
            for _, r in tops.iterrows():
                color = PALETA["rojo_suave"] if r["score"] < 0 else PALETA["verde_suave"]
                signo = "+" if r["score"] >= 0 else ""
                texto = safe(r["texto"][:140])
                handle = safe(r["handle"])
                url = safe(r["url_post"])
                st.markdown(
                    f'<div style="border-left:2px solid {color};padding:4px 10px;'
                    f'margin-bottom:4px;font-size:11px;color:#C8D0DC;line-height:1.4;">'
                    f'{texto}'
                    f'<div style="color:#6B7280;font-size:9.5px;margin-top:3px;'
                    f'font-family:JetBrains Mono;">'
                    f'<a href="{url}" target="_blank" style="color:#7AB3D7;text-decoration:none;">@{handle}</a>'
                    f' · <span style="color:{color}">{signo}{r["score"]:.2f}</span></div></div>',
                    unsafe_allow_html=True,
                )


# ═══ EVENTOS DESTACADOS ══════════════════════════════════════════════════════
if not df_rss.empty:
    atq_72h = df_rss[
        df_rss["es_ataque_refineria"]
        & (df_rss["fecha"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=72))
    ]
    if not atq_72h.empty:
        st.markdown('<h2>Refinerías · alertas 72h</h2>', unsafe_allow_html=True)
        section_desc(
            "Eventos de los feeds RSS clasificados como ataques a infraestructura de "
            "refinación en las últimas 72 horas. El matching es por keywords sobre "
            "titular y resumen — puede haber falsos positivos en notas retrospectivas."
        )
        for _, r in atq_72h.head(8).iterrows():
            ts = r["fecha"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if pd.notna(ts) else ""
            url = safe(r.get("url", ""))
            titulo = safe((r.get("titulo") or "")[:200])
            fuente = safe(r.get("fuente", ""))
            link = f'<a href="{url}" target="_blank">{titulo}</a>' if url else titulo
            st.markdown(
                f'<div class="evento alerta">'
                f'<div class="titulo">{link}</div>'
                f'<div class="meta">{fuente} · {ts_str} · {hace_cuanto(ts)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ═══ PIRATERÍA MARÍTIMA ══════════════════════════════════════════════════════
if not df_rss.empty and "es_pirateria" in df_rss.columns:
    pir_7d = df_rss[
        df_rss["es_pirateria"]
        & (df_rss["fecha"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7))
    ].sort_values("fecha", ascending=False)

    if not pir_7d.empty:
        pir_24h = int(
            pir_7d[pir_7d["fecha"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)].shape[0]
        )
        st.markdown('<h2>Ataques a buques · 7 días</h2>', unsafe_allow_html=True)
        section_desc(
            "Incidentes contra el shipping mercante: piratería clásica (abordaje, secuestro, "
            "ransom) <em>más</em> ataques militares/asimétricos (drones y misiles Houthi en "
            "el Mar Rojo y Bab el-Mandeb, ataques contra tanqueros). Ventana de 7 días porque "
            "estos eventos quedan solapados en la cobertura mediática de conflicto. Fuentes "
            "confiables: <em>IMB Piracy Reporting Centre</em>, <em>UKMTO</em>, <em>EU NAVFOR</em>, "
            "<em>Ambrey</em>. El matching es por keywords sobre titular y resumen — puede haber "
            "falsos positivos. "
            f"<strong>{len(pir_7d)} eventos en 7d</strong>"
            f"{f' · {pir_24h} en últimas 24h' if pir_24h else ''}."
        )
        for _, r in pir_7d.head(10).iterrows():
            ts = r["fecha"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if pd.notna(ts) else ""
            url = safe(r.get("url", ""))
            titulo = safe((r.get("titulo") or "")[:200])
            fuente = safe(r.get("fuente", ""))
            link = f'<a href="{url}" target="_blank">{titulo}</a>' if url else titulo
            horas = (datetime.now(timezone.utc) - ts).total_seconds() / 3600 if pd.notna(ts) else 999
            chip_html = chip("URGENTE", "alert") if horas <= 24 else ""
            st.markdown(
                f'<div class="evento alerta">'
                f'<div class="titulo">{link} {chip_html}</div>'
                f'<div class="meta">{fuente} · {ts_str} · {hace_cuanto(ts)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ═══ COMMODITIES SECTORIALES (expandible al final) ═══════════════════════════
with st.expander("Commodities sectoriales — destilados, petquím, fertilizantes, fletes, refinerías, LNG, defensa, macro", expanded=False):
    section_desc(
        "Tickers complementarios agrupados por dimensión analítica. Para muchos productos "
        "(petroquímicos, fertilizantes, fletes) los precios spot son por suscripción — usamos "
        "<em>equity proxies</em> de los mayores productores como aproximación diaria gratuita. "
        "Cada tabla muestra precio actual, variación %, y sparkline 30d."
    )
    cfg_comm = cargar("commodities.yaml")
    tabs = st.tabs(["Destilados", "Petquím", "Fertilizantes", "Tankers", "Refinerías", "LNG", "Defensa", "Macro"])
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

    def render_grupo_compact(items, dias=180):
        rows, series_dict = [], {}
        for it in items:
            c = cotizacion_actual(it["ticker"])
            s = serie_historica(it["ticker"], dias=dias)
            if not s.empty:
                series_dict[it["ticker"]] = s
            rows.append({
                "Nombre": it["nombre"],
                "Ticker": it["ticker"],
                "Precio": c["precio"] if c else None,
                "Var %": c["variacion_pct"] if c else None,
                "30d": s["cierre"].tail(30).tolist() if not s.empty else [],
            })
        df_t = pd.DataFrame(rows)
        st.dataframe(
            df_t, use_container_width=True, hide_index=True,
            column_config={
                "Precio": st.column_config.NumberColumn(format="%.2f"),
                "Var %": st.column_config.NumberColumn(format="%+.2f%%"),
                "30d": st.column_config.LineChartColumn(width="medium"),
                "Ticker": st.column_config.TextColumn(width="small"),
            },
        )

    for clave, tab in grupos:
        with tab:
            render_grupo_compact(cfg_comm.get(clave, []))


# ═══ FOOTER ──────────────────────────────────────────────────────────────────
st.markdown('<h2>Estado de fuentes</h2>', unsafe_allow_html=True)
section_desc(
    "Salud de las cuatro fuentes de datos del dashboard. "
    "<em>yfinance</em> (precios delayed 15-20m), <em>PortWatch</em> (lag semanal), "
    "<em>RSS+GDELT</em> (cerca de tiempo real), <em>Bluesky</em> AppView público (cerca de tiempo real). "
    "Si alguna entra en estado <em>down</em>, los KPIs asociados aparecen como <em>s/d</em>."
)
fc1, fc2, fc3, fc4 = st.columns(4)
yf_state = "ok" if (brent and wti) else "down"
yf_ts = datetime.now(timezone.utc).strftime("%H:%M UTC") if yf_state == "ok" else "—"
fc1.markdown(health_row("yfinance", yf_state, yf_ts), unsafe_allow_html=True)

pw_state, pw_ts = "down", "—"
if not df_cp.empty:
    ult_cp = df_cp["fecha"].max()
    lag_d = (pd.Timestamp.now(tz="UTC") - ult_cp).days
    pw_state = "warn" if lag_d > 7 else "ok"
    pw_ts = f"lag {lag_d}d"
fc2.markdown(health_row("PortWatch", pw_state, pw_ts), unsafe_allow_html=True)

rss_state = "ok" if not df_rss.empty else "down"
rss_ts = f"{len(df_rss)} items" if rss_state == "ok" else "—"
fc3.markdown(health_row("RSS + GDELT", rss_state, rss_ts), unsafe_allow_html=True)

bsky_state = "ok" if not df_bsky.empty else "down" if n_posts_total == 0 else "warn"
extra = (
    f" · {score_data['n_descartados_lang']} non-EN"
    if score_data.get("n_descartados_lang", 0) > 0 else ""
)
bsky_ts = (
    f"{n_posts_relevantes}/{n_posts_total} relevantes{extra}"
    if n_posts_total > 0 else "—"
)
fc4.markdown(health_row("Bluesky", bsky_state, bsky_ts), unsafe_allow_html=True)

st.markdown(
    f'<div style="text-align:center;color:#4B5563;font-size:10px;'
    f'font-family:JetBrains Mono;margin-top:24px;letter-spacing:0.1em;">'
    f'Auto-refresh 2 min · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}'
    f'</div>',
    unsafe_allow_html=True,
)
