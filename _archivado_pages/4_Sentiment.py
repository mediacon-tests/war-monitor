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
from fuentes.bluesky import fetch_todas_cuentas
from fuentes.sentiment import aplicar_sentiment, agregar_ponderado, score_global

st.set_page_config(page_title="Sentiment — War Monitor", page_icon="🧭", layout="wide")
inject_css()
st_autorefresh(interval=300_000, key="auto_sent")

cuentas_cfg = cargar("cuentas_bluesky.yaml")

with st.sidebar:
    st.markdown("### Sentiment")
    ventana_horas = st.selectbox("Ventana", [6, 12, 24, 48, 72, 168], index=2)
    bucket_filter = st.multiselect(
        "Buckets", list(cuentas_cfg.keys()), default=list(cuentas_cfg.keys()),
    )
    limit_por_cuenta = st.slider("Posts por cuenta", 10, 50, 30)
    solo_ingles = st.checkbox(
        "Solo posts en inglés (recomendado)", value=True,
        help="VADER es lexicón inglés; en otros idiomas devuelve ~0 sesgando al neutro.",
    )

with st.spinner("Cargando posts de Bluesky…"):
    df = fetch_todas_cuentas(cuentas_cfg, limit_por_cuenta=limit_por_cuenta)

if df.empty:
    status_bar("ELEVATED", "Sentiment OSINT · Bluesky")
    st.markdown("# Sentiment OSINT")
    st.warning(
        "No se obtuvieron posts. Causas posibles: cuentas inexistentes, "
        "Bluesky AppView caído, o ningún handle marcado `activo: true` en config."
    )
    st.stop()

if "bucket" in df.columns:
    df = df[df["bucket"].isin(bucket_filter)].copy()
if df.empty:
    status_bar("ELEVATED", "Sentiment OSINT · Bluesky")
    st.markdown("# Sentiment OSINT")
    st.info("Sin posts para los buckets seleccionados.")
    st.stop()

df = aplicar_sentiment(df, columna_texto="texto", solo_ingles=solo_ingles)
g = score_global(df, ventana_horas=ventana_horas)
score = g["score"]

# Score previo (ventana anterior) para delta
desde_ant = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=ventana_horas * 2)
hasta_ant = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=ventana_horas)
df_prev = df[(df["creado_en"] >= desde_ant) & (df["creado_en"] < hasta_ant)].dropna(subset=["score"])
if not df_prev.empty:
    g_prev = score_global(
        df.assign(creado_en=df["creado_en"] + pd.Timedelta(hours=ventana_horas)),
        ventana_horas=ventana_horas,
    )
    score_prev = g_prev["score"] if g_prev["n_posts"] > 0 else 0.0
else:
    score_prev = 0.0
delta_score = score - score_prev

# Status bar
nivel_pag = "ELEVATED"
sub_pag = f"Bluesky · {g['n_cuentas']} cuentas"
if score <= -0.4 and g["n_cuentas"] >= 3:
    nivel_pag = "HIGH"
    sub_pag = f"sentiment {score:+.2f} sobre {g['n_cuentas']} cuentas"

status_bar(nivel_pag, sub_pag)
st.markdown("# Sentiment OSINT")
st.caption(
    "Agregación en dos pasos: media por cuenta, luego promedio ponderado entre cuentas. "
    f"VADER inglés. {'Posts no-inglés descartados.' if solo_ingles else 'Posts mixtos incluidos.'} "
    "Score ∈ [-1, +1]. Refleja el universo curado, no opinión pública general."
)

# --- Hero: gauge + KPIs ---
col_g, col_kpis = st.columns([2, 3])

with col_g:
    fig_g = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(score),
        number={"valueformat": "+.2f", "font": {"size": 44, "color": PALETA["texto"]}},
        gauge={
            "axis": {"range": [-1, 1], "tickcolor": PALETA["texto_2"],
                      "tickfont": {"color": PALETA["texto_2"], "size": 10}},
            "bar": {
                "color": PALETA["rojo"] if score < -0.3
                else PALETA["verde"] if score > 0.3
                else PALETA["azul"],
                "thickness": 0.25,
            },
            "bgcolor": PALETA["fondo_panel"],
            "borderwidth": 0,
            "steps": [
                {"range": [-1, -0.5], "color": "#B33A3A55"},
                {"range": [-0.5, -0.15], "color": "#D97A2C44"},
                {"range": [-0.15, 0.15], "color": "#2A323D"},
                {"range": [0.15, 0.5], "color": "#3F8F5C44"},
                {"range": [0.5, 1], "color": "#3F8F5C77"},
            ],
            "threshold": {
                "line": {"color": PALETA["texto"], "width": 3},
                "thickness": 0.85, "value": float(score),
            },
        },
    ))
    aplicar(fig_g, height=280, margin=dict(l=20, r=20, t=20, b=10),
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"])
    st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})

    delta_html = f"vs {ventana_horas}h previas: <strong>{delta_score:+.2f}</strong>"
    if delta_score < -0.1:
        ctx = chip("DETERIORO", "disrupt")
    elif delta_score > 0.1:
        ctx = chip("MEJORA", "ok")
    else:
        ctx = chip("ESTABLE", "info")
    st.markdown(
        f'<div style="text-align:center;color:#A0A8B4;font-family:Inter;font-size:13px;">'
        f'{delta_html} {ctx}</div>',
        unsafe_allow_html=True,
    )

with col_kpis:
    sub = df[
        (df["creado_en"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=ventana_horas))
    ]
    cc = st.columns(3)
    cc[0].markdown(kpi_card(
        "Posts en ventana", str(g["n_posts"]), None,
        f"últimas {ventana_horas}h" + (
            f" · {g['n_descartados_lang']} non-EN" if g.get("n_descartados_lang", 0) else ""
        ),
        color_borde=PALETA["azul"],
    ), unsafe_allow_html=True)
    cc[1].markdown(kpi_card(
        "Cuentas activas", str(g["n_cuentas"]), None,
        "de las activas en config",
        color_borde=PALETA["violeta"],
    ), unsafe_allow_html=True)
    engagement = int(sub["likes"].sum() + sub["reposts"].sum()) if not sub.empty else 0
    cc[2].markdown(kpi_card(
        "Engagement", f"{engagement:,}", None, "♥ + ↻",
        color_borde=PALETA["ambar"],
    ), unsafe_allow_html=True)

    # Por bucket
    st.markdown("##### Score por bucket")
    bucket_scores = []
    for b, gd in sub.dropna(subset=["score"]).groupby("bucket"):
        if gd.empty:
            continue
        # Usar 2-step también por bucket
        por_handle = gd.groupby("handle").agg(s=("score", "mean"), p=("peso", "first")).reset_index()
        if por_handle["p"].sum() > 0:
            s_bucket = (por_handle["s"] * por_handle["p"]).sum() / por_handle["p"].sum()
        else:
            s_bucket = float(por_handle["s"].mean())
        bucket_scores.append({"bucket": b, "score": float(s_bucket), "n_posts": len(gd)})
    if bucket_scores:
        bs_df = pd.DataFrame(bucket_scores).sort_values("score")
        fig_b = go.Figure(go.Bar(
            x=bs_df["score"], y=bs_df["bucket"], orientation="h",
            marker_color=[
                PALETA["rojo"] if s < -0.1 else PALETA["verde"] if s > 0.1 else PALETA["azul"]
                for s in bs_df["score"]
            ],
            text=[f"{s:+.2f} ({n})" for s, n in zip(bs_df["score"], bs_df["n_posts"])],
            textposition="auto",
            hovertemplate="%{y}<br>score: %{x:.2f}<extra></extra>",
        ))
        aplicar(fig_b, height=210, xaxis=dict(range=[-1, 1]),
                margin=dict(l=10, r=10, t=10, b=20),
                paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"])
        st.plotly_chart(fig_b, use_container_width=True, config={"displayModeBar": False})

st.markdown("")

# --- Serie temporal ---
st.markdown("### Evolución del sentiment")
freq_map = {6: "30min", 12: "1h", 24: "1h", 48: "2h", 72: "3h", 168: "6h"}
ts_serie = agregar_ponderado(df.dropna(subset=["score"]), ventana=freq_map.get(ventana_horas, "1h"))
if not ts_serie.empty and "score_pond" in ts_serie.columns:
    fig_t = go.Figure()
    fig_t.add_trace(go.Scatter(
        x=ts_serie["creado_en"], y=ts_serie["score_pond"],
        mode="lines+markers", line=dict(color=PALETA["azul"], width=2),
        marker=dict(size=5, color=PALETA["azul"]),
        name="Score ponderado",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>score: %{y:+.2f}<extra></extra>",
    ))
    fig_t.add_hline(y=0, line=dict(color=PALETA["borde"], width=1, dash="dash"))
    aplicar(fig_t, height=320, yaxis=dict(range=[-1, 1]), hovermode="x unified",
            yaxis_title="Score [-1, +1]",
            paper_bgcolor=PALETA["fondo_app"], plot_bgcolor=PALETA["fondo_app"])
    st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})

# --- Posts extremos ---
st.markdown("### Posts más extremos")
sub_v = df[df["creado_en"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=ventana_horas)]
sub_v = sub_v.dropna(subset=["score"])
col_neg, col_pos = st.columns(2)


def render_posts(grupo, titulo, color):
    if grupo.empty:
        st.markdown(f"**{titulo}** — sin posts")
        return
    st.markdown(f"**{titulo}**")
    for _, r in grupo.iterrows():
        signo = "+" if r["score"] >= 0 else ""
        url = safe(r["url_post"])
        handle = safe(r["handle"])
        texto = safe(r["texto"][:240])
        st.markdown(
            f"""
            <div class="panel" style="border-left:3px solid {color};padding:8px 12px;margin-bottom:6px;">
              <div style="color:#E6EAF2;font-size:12px;line-height:1.4;">{texto}</div>
              <div style="font-size:10px;color:#6B7280;font-family:'JetBrains Mono',monospace;margin-top:6px;">
                <a href="{url}" target="_blank" style="color:#C9A227;">@{handle}</a>
                · score <strong style="color:{color};">{signo}{r['score']:.2f}</strong>
                · {hace_cuanto(r['creado_en'])}
                · ♥ {int(r['likes'])} ↻ {int(r['reposts'])}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


with col_neg:
    render_posts(sub_v.sort_values("score").head(5), "Más negativos", PALETA["rojo_suave"])
with col_pos:
    render_posts(sub_v.sort_values("score", ascending=False).head(5), "Más positivos", PALETA["verde_suave"])

# --- Health ---
with st.expander("Estado de cuentas Bluesky"):
    activas, inactivas = [], []
    handles_en_df = set(df["handle"].unique()) if not df.empty else set()
    for bucket, lst in cuentas_cfg.items():
        if not isinstance(lst, list):
            continue
        for c in lst:
            if not c.get("activo", False):
                continue
            (activas if c["handle"] in handles_en_df else inactivas).append(c)
    st.markdown(f"**Funcionando: {len(activas)}** · **Caídas: {len(inactivas)}**")
    if inactivas:
        st.markdown("Caídas (verificar handles):")
        for c in inactivas:
            st.markdown(f"  - `{safe(c['handle'])}` ({safe(c.get('nombre','?'))})")

panel_footer("Bluesky AppView público · vaderSentiment")
