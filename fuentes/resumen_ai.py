"""Resumen narrativo del estado actual generado por Claude.

Si la env var `ANTHROPIC_API_KEY` está seteada, usa Claude Haiku 4.5 (modelo rápido
y barato, ideal para 1 párrafo). Si no, cae a un resumen rule-based que arma una
síntesis a partir de los mismos datos.
"""
from __future__ import annotations
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from utiles.secretos import obtener as obtener_secret


SYSTEM_PROMPT = """Sos un analista senior de mercados de energía y geopolítica del Golfo Pérsico (perfil tipo Helima Croft / Javier Blas). Estás leyendo un dashboard de monitoreo del conflicto Irán ↔ EE.UU. / Israel y tenés que producir un párrafo conciso (máximo 5 líneas) que resuma el estado actual.

Reglas:
- Escribir en español neutro/rioplatense, prosa profesional pero directa.
- Foco en señales accionables: tightness del crudo, disrupción física en chokepoints, riesgo geopolítico, sentiment OSINT.
- Usar SOLO los datos provistos. NO inventar números, eventos ni declaraciones.
- Si los datos son ambiguos, contradictorios o están con lag, decirlo explícitamente.
- Sin bullets ni listas — un párrafo corrido.
- Sin emojis ni markdown. Texto plano.
- No saludar ni cerrar con conclusiones genéricas. Empezar directo con la situación."""


def _construir_contexto(datos: dict) -> str:
    """Arma el bloque de datos que se le pasa al modelo (o se usa para el fallback)."""
    lineas = []
    lineas.append(f"Fecha del análisis: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lineas.append(f"Nivel global del dashboard: {datos.get('nivel', 'N/A')} ({datos.get('razones', '')})")
    lineas.append("")
    lineas.append("MERCADOS:")
    if datos.get("brent"):
        b = datos["brent"]
        lineas.append(f"- Brent: ${b['precio']:.2f}/bbl ({b['variacion_pct']:+.2f}%)")
    if datos.get("wti"):
        w = datos["wti"]
        lineas.append(f"- WTI: ${w['precio']:.2f}/bbl ({w['variacion_pct']:+.2f}%)")
    if datos.get("spread") is not None:
        lineas.append(f"- Spread WTI-Brent: ${datos['spread']:+.2f}/bbl")
    if datos.get("ovx"):
        lineas.append(f"- ^OVX (vol crudo): {datos['ovx']['precio']:.2f} ({datos['ovx']['variacion_pct']:+.2f}%)")
    if datos.get("hsi") is not None:
        lineas.append(f"- Hormuz Stress Index: {datos['hsi']:+.2f} (>1.5 = stress)")
    lineas.append("")
    lineas.append("CHOKEPOINTS (tanqueros/día, baseline = mediana mismo DOW últimos 90d):")
    for cp in datos.get("chokepoints", []):
        z = f"{cp['z_score']:.2f}" if cp['z_score'] is not None else "—"
        d = f"{cp['desvio_pct']:+.0f}%" if cp['desvio_pct'] is not None else "—"
        lineas.append(
            f"- {cp['nombre']}: actual {cp['actual']:.0f}, baseline {cp['baseline']:.0f}, "
            f"desvío {d}, z={z}, lag {cp['lag_dias']}d"
        )
    lineas.append("")
    lineas.append("INTELIGENCIA ABIERTA:")
    lineas.append(
        f"- Sentiment OSINT 24h (Bluesky, VADER, ponderado por handle): "
        f"{datos.get('sentiment_score', 0):+.2f} sobre {datos.get('sentiment_cuentas', 0)} cuentas / {datos.get('sentiment_posts', 0)} posts"
    )
    if datos.get("ataques_72h", 0) > 0:
        lineas.append(f"- Ataques a refinerías últimas 72h: {datos['ataques_72h']}")
    if datos.get("eventos_recientes"):
        lineas.append("- Titulares recientes:")
        for e in datos["eventos_recientes"][:6]:
            lineas.append(f"  · [{e['fuente']}] {e['titulo'][:140]}")
    return "\n".join(lineas)


def _resumen_rule_based(datos: dict) -> str:
    """Fallback sin LLM. Arma un párrafo con plantillas en base a los datos."""
    partes = []

    # Mercados
    if datos.get("brent") and datos.get("wti"):
        b, w = datos["brent"], datos["wti"]
        spread = w["precio"] - b["precio"]
        if abs(b["variacion_pct"]) >= 3:
            partes.append(
                f"Brent cotiza en USD {b['precio']:.2f} con un movimiento de {b['variacion_pct']:+.1f}% "
                f"que sugiere tensión en el mercado."
            )
        else:
            partes.append(f"Brent en USD {b['precio']:.2f} ({b['variacion_pct']:+.1f}%) y WTI en USD {w['precio']:.2f}.")
        if spread > 3 or spread < -10:
            partes.append(f"El spread WTI-Brent en USD {spread:+.2f} muestra dislocación del arbitraje.")

    # Chokepoints
    cps_disrupt = [c for c in datos.get("chokepoints", []) if c["z_score"] is not None and c["z_score"] <= -2.0]
    cps_alerta = [c for c in datos.get("chokepoints", []) if c["z_score"] is not None and -2.0 < c["z_score"] <= -1.0]
    if cps_disrupt:
        nombres = ", ".join(c["nombre"] for c in cps_disrupt)
        lag = max(c["lag_dias"] for c in cps_disrupt)
        partes.append(
            f"En tránsito de tanqueros, {nombres} muestra disrupción severa "
            f"(z<=-2) con datos de hace {lag} días."
        )
    elif cps_alerta:
        nombres = ", ".join(c["nombre"] for c in cps_alerta)
        partes.append(f"{nombres} con tránsito por debajo del baseline pero sin disrupción aguda.")
    else:
        partes.append("Los tres chokepoints clave operan en torno a sus baselines históricos.")

    # HSI
    hsi = datos.get("hsi")
    if hsi is not None:
        if hsi >= 1.5:
            partes.append(f"El Hormuz Stress Index está en {hsi:+.2f} (stress agudo).")
        elif hsi >= 0.5:
            partes.append(f"HSI en {hsi:+.2f} indica tensión elevada en el complejo crudo/macro.")

    # Refinerías
    if datos.get("ataques_72h", 0) > 0:
        partes.append(f"Se reportaron {datos['ataques_72h']} eventos de ataques a refinerías en las últimas 72h.")

    # Sentiment
    s = datos.get("sentiment_score", 0)
    n_c = datos.get("sentiment_cuentas", 0)
    if n_c >= 3:
        if s <= -0.4:
            partes.append(f"El sentiment OSINT está marcadamente negativo ({s:+.2f}) sobre {n_c} cuentas.")
        elif s <= -0.2:
            partes.append(f"OSINT con tono negativo moderado ({s:+.2f}) sobre {n_c} cuentas.")
        elif s >= 0.2:
            partes.append(f"OSINT con tono positivo ({s:+.2f}) sobre {n_c} cuentas.")

    return " ".join(partes) if partes else "Datos insuficientes para una síntesis significativa."


@st.cache_data(ttl=86400, show_spinner=False)
def _generar_cached(contexto: str, session_key: int) -> tuple[str, str]:
    """Cache real con TTL de 24h. La clave incluye `session_key`, que cambia
    con cada F5 del browser o cuando el usuario clickea "Regenerar".
    Auto-refresh (st_autorefresh) NO cambia session_key → reutiliza el cache.
    """
    api_key = obtener_secret("ANTHROPIC_API_KEY")
    if not api_key:
        return "", "rule-based (sin ANTHROPIC_API_KEY)"

    try:
        import anthropic
    except ImportError:
        return "", "rule-based (anthropic no instalado)"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": contexto}],
        )
        texto = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        if not texto:
            return "", "rule-based (respuesta vacía)"
        return texto, "claude-haiku-4-5"
    except Exception as e:
        return "", f"rule-based (error API: {type(e).__name__})"


def generar_resumen(datos_dict: dict, session_key: int) -> tuple[str, str]:
    """Devuelve (texto_resumen, fuente_modelo).

    Cachea por (contexto, session_key). Una llamada por F5 / botón Regenerar.
    """
    contexto = _construir_contexto(datos_dict)
    texto, modelo = _generar_cached(contexto, session_key)
    if not texto:
        return _resumen_rule_based(datos_dict), modelo
    return texto, modelo
