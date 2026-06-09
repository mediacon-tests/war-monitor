"""Tema visual unificado para Plotly. Importar y aplicar a cada figura."""
from copy import deepcopy

PALETA = {
    "fondo_app": "#0B0F14",
    "fondo_panel": "#11161D",
    "fondo_elev": "#1A2129",
    "borde": "#2A323D",
    "borde_hover": "#3A4250",
    "texto": "#E6EAF2",
    "texto_2": "#A0A8B4",
    "texto_3": "#6B7280",
    "ambar": "#C9A227",
    "azul": "#4A90C2",
    "rojo": "#B33A3A",
    "verde": "#3F8F5C",
    "violeta": "#8B6FB8",
    "naranja": "#D97A2C",
    "rojo_suave": "#D97A7A",
    "verde_suave": "#7FB893",
}

LAYOUT = dict(
    paper_bgcolor=PALETA["fondo_app"],
    plot_bgcolor=PALETA["fondo_app"],
    font=dict(family="Inter, sans-serif", color=PALETA["texto"], size=12),
    xaxis=dict(
        gridcolor=PALETA["fondo_elev"],
        zerolinecolor=PALETA["borde"],
        linecolor=PALETA["borde"],
        tickfont=dict(color=PALETA["texto_2"], size=11),
        showspikes=False,
    ),
    yaxis=dict(
        gridcolor=PALETA["fondo_elev"],
        zerolinecolor=PALETA["borde"],
        linecolor=PALETA["borde"],
        tickfont=dict(color=PALETA["texto_2"], size=11),
    ),
    colorway=[
        PALETA["ambar"],
        PALETA["azul"],
        PALETA["naranja"],
        PALETA["violeta"],
        PALETA["verde"],
        PALETA["rojo"],
    ],
    hoverlabel=dict(
        bgcolor=PALETA["fondo_elev"],
        bordercolor=PALETA["borde"],
        font=dict(family="JetBrains Mono, monospace", size=11, color=PALETA["texto"]),
    ),
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETA["texto_2"], size=11),
    ),
)

SPARKLINE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=0, b=0),
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
    showlegend=False,
    height=50,
)


def aplicar(fig, **overrides):
    layout = deepcopy(LAYOUT)
    layout.update(overrides)
    fig.update_layout(**layout)
    return fig


def aplicar_sparkline(fig, color: str | None = None):
    fig.update_layout(**SPARKLINE)
    if color:
        fig.update_traces(line=dict(width=1.5, color=color))
    return fig
