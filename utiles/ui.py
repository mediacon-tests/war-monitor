"""Componentes UI reutilizables y CSS global del dashboard."""
import html as _html
import streamlit as st
from datetime import datetime, timezone

from utiles.plot_theme import PALETA


def safe(s) -> str:
    """Escapa HTML para inyección segura en plantillas con unsafe_allow_html."""
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


CSS_GLOBAL = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; }
.stApp { background: #0B0F14; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1480px; }

/* Esconder sidebar y header default de Streamlit */
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stToolbar"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* Tabular nums en métricas y números */
[data-testid="stMetricValue"], .mono {
  font-family: 'JetBrains Mono', monospace !important;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

/* Tipografía minimalista */
h1, h2, h3 { letter-spacing: -0.01em; margin: 0; }
h1 { font-weight: 500; font-size: 18px !important; color: #E6EAF2 !important; padding: 0; }
h2 { font-weight: 400; font-size: 11px !important; color: #6B7280 !important;
     text-transform: uppercase; letter-spacing: 0.16em; margin-top: 2rem !important;
     margin-bottom: 0.6rem !important; padding-bottom: 0.4rem;
     border-bottom: 1px solid #1A2129; }
h3 { font-weight: 500; font-size: 12px !important; color: #A0A8B4 !important; }

/* Header de aplicación: una línea sutil */
.app-header {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 4px 0 14px 0; margin-bottom: 8px;
  border-bottom: 1px solid #1A2129;
}
.app-header .titulo {
  font-size: 13px; color: #E6EAF2; font-weight: 500;
  letter-spacing: 0.10em; text-transform: uppercase;
}
.app-header .meta {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: #6B7280; letter-spacing: 0.04em;
}
.app-header .meta .level-low    { color: #7FB893; }
.app-header .meta .level-elev   { color: #C9A227; }
.app-header .meta .level-high   { color: #D97A2C; }
.app-header .meta .level-crit   { color: #B33A3A; }

/* KPI Card minimalista — sin border-left por defecto */
.kpi {
  background: #11161D; border: 1px solid #1F2630; border-radius: 4px;
  padding: 12px 14px; height: 96px;
  display: flex; flex-direction: column; justify-content: space-between;
  transition: border-color 0.2s;
}
.kpi.alert { border-left: 2px solid #B33A3A; }
.kpi.warn  { border-left: 2px solid #C9A227; }
.kpi.xl { height: 116px; padding: 14px 18px; }

.kpi .label {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.10em;
  color: #6B7280; font-weight: 500; line-height: 1.2;
  display: flex; justify-content: space-between; align-items: center;
}
.kpi .value {
  font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums;
  font-size: 24px; font-weight: 500; color: #E6EAF2;
  letter-spacing: -0.02em; line-height: 1.1; margin: 4px 0 2px 0;
}
.kpi.xl .value { font-size: 32px; font-weight: 500; }
.kpi .delta {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
}
.kpi .delta.up { color: #7FB893; }
.kpi .delta.dn { color: #D97A7A; }
.kpi .delta.flat { color: #6B7280; }
.kpi .ts {
  font-size: 9.5px; color: #4B5563;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  letter-spacing: 0.04em;
}

/* Chip — solo aparece para alertas/contexto crítico */
.chip {
  display:inline-block; padding:1px 6px; border-radius:2px;
  font-size:9px; font-weight:500; text-transform:uppercase;
  letter-spacing:0.08em; font-family:'Inter',sans-serif;
}
.chip-alert { background:#B33A3A22; color:#D97A7A; border:1px solid #B33A3A55; }
.chip-warn  { background:#C9A22722; color:#C9A227; border:1px solid #C9A22755; }
.chip-ok    { background:#3F8F5C22; color:#7FB893; border:1px solid #3F8F5C55; }
.chip-info  { background:#4A90C222; color:#7AB3D7; border:1px solid #4A90C255; }

/* Tape feed (eventos) */
.tape {
  background: transparent; border: 1px solid #1F2630; border-radius: 4px;
  padding: 8px 10px; max-height: 380px; overflow-y: auto;
  font-family: 'JetBrains Mono', monospace; font-size: 11.5px;
  -webkit-mask-image: linear-gradient(to bottom, black calc(100% - 24px), transparent 100%);
          mask-image: linear-gradient(to bottom, black calc(100% - 24px), transparent 100%);
}
.tape::-webkit-scrollbar { width: 4px; }
.tape::-webkit-scrollbar-thumb { background: #2A323D; border-radius: 2px; }
.tape-row {
  padding: 5px 0; border-bottom: 1px solid #14191F;
  color: #A0A8B4; line-height: 1.45;
}
.tape-row:last-child { border-bottom: none; }
.tape-row .ts { color: #4B5563; margin-right: 8px; font-size: 9.5px; }
.tape-row .src { color: #6B7280; margin-right: 6px; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.06em; }
.tape-row.alerta { color: #E6EAF2; }
.tape-row.alerta .src { color: #D97A7A; }
.tape-row a { color: inherit; text-decoration: none; }
.tape-row a:hover { color: #E6EAF2; }

/* Card de evento sutil */
.evento {
  padding: 8px 12px; margin-bottom: 4px;
  border-bottom: 1px solid #14191F;
}
.evento:last-child { border-bottom: none; }
.evento .titulo { color: #E6EAF2; font-size: 12.5px; font-weight: 400; line-height: 1.4; }
.evento .meta {
  color: #6B7280; font-size: 10px; margin-top: 3px;
  font-family: 'JetBrains Mono', monospace; letter-spacing: 0.03em;
}
.evento.alerta {
  background: linear-gradient(180deg, #B33A3A12 0%, transparent 100%);
  border-left: 2px solid #B33A3A55; padding-left: 10px;
}
.evento a { color: inherit; text-decoration: none; }
.evento a:hover { color: #C9A227; }

/* Health row */
.health-row {
  display: flex; align-items: center; padding: 3px 0;
  font-family: 'JetBrains Mono', monospace; font-size: 10.5px;
  color: #6B7280; letter-spacing: 0.03em;
}
.health-row .nombre { flex: 1; color: #A0A8B4; }
.health-row .ts { color: #4B5563; }
.health-row .dot {
  display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:8px;
}
.dot-ok    { background:#3F8F5C; }
.dot-warn  { background:#C9A227; }
.dot-down  { background:#B33A3A; }
.dot-stale { background:#3A4250; }

/* Tabs sobrios */
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid #1F2630; }
.stTabs [data-baseweb="tab"] {
  background: transparent; border-radius: 0;
  padding: 6px 14px; font-size: 11px; font-weight: 400;
  color: #6B7280; border-bottom: 1px solid transparent;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.stTabs [aria-selected="true"] {
  background: transparent !important; color: #E6EAF2 !important;
  border-bottom: 1px solid #4A90C2 !important;
}

/* Caption más sutil */
.stCaption, [data-testid="stCaptionContainer"] {
  font-size: 10.5px !important; color: #6B7280 !important;
}

/* Descripción de sección debajo del h2 */
.section-desc {
  font-size: 11px; color: #6B7280; line-height: 1.5;
  margin: -4px 0 14px 0; max-width: 880px;
  letter-spacing: 0.01em;
}
.section-desc em { color: #A0A8B4; font-style: normal; }

/* Botón "regenerar IA" sutil */
.stButton button[kind="secondary"], .stButton button {
  background: transparent !important;
  border: 1px solid #2A323D !important;
  color: #A0A8B4 !important;
  font-size: 11px !important;
  font-family: 'JetBrains Mono', monospace !important;
  padding: 3px 10px !important;
  border-radius: 3px !important;
  letter-spacing: 0.04em;
  margin-top: -14px;
}
.stButton button:hover {
  border-color: #4A90C2 !important;
  color: #E6EAF2 !important;
}

/* Brief (resumen IA) */
.brief {
  background: #11161D;
  border: 1px solid #1F2630;
  border-left: 2px solid #4A90C2;
  border-radius: 4px;
  padding: 14px 18px;
  margin: 8px 0 22px 0;
}
.brief .brief-label {
  font-size: 9.5px; color: #6B7280;
  text-transform: uppercase; letter-spacing: 0.14em;
  margin-bottom: 8px; font-weight: 500;
  display: flex; justify-content: space-between; align-items: center;
}
.brief .brief-label .modelo {
  font-family: 'JetBrains Mono', monospace; color: #4B5563;
  text-transform: none; letter-spacing: 0.04em; font-size: 9px;
}
.brief .brief-text {
  color: #C8D0DC; font-size: 13px; line-height: 1.6;
  font-weight: 300;
}

/* Plotly: legends en monospace para alineación con tabular nums */
.plotly .legend text { font-family: 'JetBrains Mono', monospace !important; }
</style>
"""


def inject_css():
    """Inyectar el CSS global. Llamar al inicio de la app."""
    st.markdown(CSS_GLOBAL, unsafe_allow_html=True)


def chip(texto: str, tipo: str = "info") -> str:
    """tipo: alert | warn | ok | info"""
    return f'<span class="chip chip-{tipo}">{safe(texto)}</span>'


def app_header(nivel: str = "ELEVATED", subtitulo: str = ""):
    nivel_clase = {
        "LOW": "level-low",
        "ELEVATED": "level-elev",
        "HIGH": "level-high",
        "CRITICAL": "level-crit",
    }.get(nivel, "level-elev")
    ahora = datetime.now(timezone.utc)
    sub_html = (
        f'<span style="margin-left:14px;color:#6B7280">{safe(subtitulo)}</span>'
        if subtitulo else ""
    )
    st.markdown(
        f"""
        <div class="app-header">
          <div class="titulo">War Monitor · Irán ↔ EE.UU. / Israel</div>
          <div class="meta">
            <span class="{nivel_clase}">● {safe(nivel)}</span>{sub_html}
            <span style="margin-left:18px;">UTC {ahora.strftime('%Y-%m-%d %H:%M:%S')}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi(
    label: str,
    valor: str,
    delta: str | None = None,
    ts: str | None = None,
    estado: str = "normal",   # normal | warn | alert
    chip_html: str = "",
    tamano: str = "md",       # md | xl
) -> str:
    """KPI minimalista. Sin border-left por default; aparece solo si estado != normal."""
    cls_size = "xl" if tamano == "xl" else ""
    cls_state = {"alert": "alert", "warn": "warn"}.get(estado, "")

    if delta is None:
        delta_html = ""
    else:
        d = str(delta).strip()
        if d.startswith("-"):
            cls = "dn"
        elif d.startswith("+"):
            cls = "up"
        else:
            cls = "flat"
        delta_html = f'<div class="delta {cls}">{safe(d)}</div>'

    ts_html = f'<div class="ts">{safe(ts)}</div>' if ts else ""

    return f"""<div class="kpi {cls_size} {cls_state}">
  <div>
    <div class="label"><span>{safe(label)}</span> {chip_html}</div>
    <div class="value">{safe(valor)}</div>
    {delta_html}
  </div>
  {ts_html}
</div>"""


def section_desc(texto: str):
    st.markdown(f'<div class="section-desc">{texto}</div>', unsafe_allow_html=True)


def brief(texto: str, modelo: str = ""):
    st.markdown(
        f"""
        <div class="brief">
          <div class="brief-label">
            <span>Resumen IA · estado actual</span>
            <span class="modelo">{safe(modelo)}</span>
          </div>
          <div class="brief-text">{safe(texto)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def health_row(nombre: str, estado: str, ts_str: str = "") -> str:
    return (
        f'<div class="health-row"><span class="dot dot-{safe(estado)}"></span>'
        f'<span class="nombre">{safe(nombre)}</span>'
        f'<span class="ts">{safe(ts_str)}</span></div>'
    )


def hace_cuanto(ts) -> str:
    if ts is None:
        return "—"
    if not isinstance(ts, datetime):
        return str(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    s = int(delta.total_seconds())
    if s < 60:
        return f"hace {s}s"
    if s < 3600:
        return f"hace {s // 60}m"
    if s < 86400:
        return f"hace {s // 3600}h"
    return f"hace {s // 86400}d"
