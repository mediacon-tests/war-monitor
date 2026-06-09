"""Sentiment geopolítico-energético usando Claude Haiku 4.5.

Reemplaza VADER cuando hay ANTHROPIC_API_KEY. Devuelve score [-1, +1] que mide
impacto sobre riesgo del conflicto/mercados de energía (no tono emocional).

Cache estrategia:
- Por `session_key` (igual que el resumen IA): cada F5 / botón regenerar = nueva sesión.
- Dentro de la sesión, cache por URI: si llegan posts nuevos, solo se clasifican los nuevos.
"""
from __future__ import annotations
import json
import re

import pandas as pd
import streamlit as st

from utiles.secretos import obtener as obtener_secret


SYSTEM_PROMPT_CLASIF = """Sos analista senior de mercados de energía y geopolítica del Golfo Pérsico (perfil tipo Helima Croft / Javier Blas / John Kemp). Te paso una lista numerada de posts de Bluesky relacionados al conflicto Irán ↔ EE.UU. / Israel y a mercados de energía.

Para cada post asigná:

1. `score` ∈ [-1.0, +1.0] sobre el impacto en RIESGO GEOPOLÍTICO-ENERGÉTICO:
   - -1.0 = escalada severa / disrupción aguda de oferta / alarma máxima
   - -0.6 = escalada moderada / retórica agresiva clara / tensión visible
   - -0.3 = leve negativo / advertencia / fricción
   -  0.0 = neutro o no informativo en este eje
   - +0.3 = leve positivo / señal de cooperación
   - +0.6 = desescalada moderada / acuerdo parcial / alivio de oferta
   - +1.0 = desescalada clara / alto el fuego / restablecimiento

2. `cat` (una de): escalada / desescalada / tension-mercado / oferta-disrupcion / oferta-restablecimiento / diplomacia / opinion / neutro

REGLAS CRÍTICAS:
- Esto NO es sentiment emocional. Foco geopolítico-energético. "Trump cancela negociaciones con Irán" suena neutral pero es ESCALADA NEGATIVA (-0.5).
- "Suben los precios del crudo por temor a Hormuz" es `tension-mercado` con score negativo (mercado pricing riesgo).
- "Houthis suspenden ataques en el Mar Rojo" es `desescalada` positiva (+0.5).
- "Iran threatens to close Hormuz" es escalada severa (-0.8).
- "Aramco increases output" es `oferta-restablecimiento` (+0.4).
- Posts NO relacionados a este eje (deportes, cultura, doméstica no-MENA): cat=neutro, score=0.
- Ambigüedad → score más cerca de 0.

DEVOLVER JSON EXACTO (sin markdown, sin code fences, sin texto adicional):
{"scores": [{"idx": 0, "score": -0.7, "cat": "escalada"}, {"idx": 1, "score": 0.0, "cat": "neutro"}]}

Números positivos SIN signo + (correcto: 0.6, incorrecto: +0.6). Solo "-" para negativos."""


def _truncar(texto: str, n: int = 280) -> str:
    return (texto or "")[:n].replace("\n", " ").strip()


@st.cache_data(ttl=86400, show_spinner=False)
def _llamar_api(textos_tuple: tuple, session_key: int) -> list[dict]:
    """Cache por (textos, session_key). Una llamada por sesión + lote de posts."""
    api_key = obtener_secret("ANTHROPIC_API_KEY")
    if not api_key or not textos_tuple:
        return []
    try:
        import anthropic
    except ImportError:
        return []

    user_prompt = "\n".join(f"[{i}] {_truncar(t)}" for i, t in enumerate(textos_tuple))

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            system=SYSTEM_PROMPT_CLASIF,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

        # 1. Si hay code fences (```json ... ```), extraer el bloque de adentro
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
        # 2. Si el modelo metió texto antes/después del JSON, recortar al primer
        #    `{` y al último `}` que cierran el objeto raíz.
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            raw = raw[i:j + 1]
        # 3. Reemplazar "+0.6" por "0.6" (JSON estándar no acepta + en números)
        raw = re.sub(r"(?<=[:\s,\[])\+(?=\d|\.)", "", raw)
        raw = raw.strip()

        data = json.loads(raw)
        scores = data.get("scores", [])
        if not isinstance(scores, list):
            return []
        return scores
    except Exception:
        return []


def aplicar_sentiment_claude(df: pd.DataFrame, session_key: int) -> pd.DataFrame:
    """Agrega columna `score` ∈ [-1, +1] y `categoria_claude` usando Claude.

    Si la API no está disponible, devuelve el DF con score=0.0 (caller debe usar fallback).
    Cache por URI dentro de la sesión: posts ya clasificados se reusan.

    Devuelve DF ampliado con `score`, `categoria_claude`, y siempre incluye
    todas las filas originales (los que no se pudieron clasificar quedan en score=0).
    """
    if df.empty or "uri" not in df.columns:
        return df

    cache_state_key = f"_sentiment_uri_map_{session_key}"
    if cache_state_key not in st.session_state:
        st.session_state[cache_state_key] = {}
    cache: dict = st.session_state[cache_state_key]

    uris = df["uri"].tolist()
    uris_faltantes = [u for u in uris if u not in cache]

    if uris_faltantes:
        textos_por_uri = dict(zip(df["uri"], df["texto"].fillna("")))
        textos_faltantes = [textos_por_uri[u] for u in uris_faltantes]
        scores_data = _llamar_api(tuple(textos_faltantes), session_key)
        for s in scores_data:
            idx = s.get("idx")
            if idx is None or not (0 <= idx < len(uris_faltantes)):
                continue
            try:
                score = float(s.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            score = max(-1.0, min(1.0, score))
            cache[uris_faltantes[idx]] = {
                "score": score,
                "cat": str(s.get("cat", "neutro")),
            }
        st.session_state[cache_state_key] = cache

    import numpy as np
    df = df.copy()
    # cat=neutro → score NaN para que score_global los descarte (consistente con
    # cómo VADER excluye posts no-inglés del promedio).
    scores = []
    cats = []
    for u in df["uri"]:
        entry = cache.get(u, {})
        cat = entry.get("cat", "neutro")
        cats.append(cat)
        if cat == "neutro":
            scores.append(np.nan)
        else:
            scores.append(entry.get("score", 0.0))
    df["score"] = scores
    df["categoria_claude"] = cats
    return df


def claude_disponible() -> bool:
    return bool(obtener_secret("ANTHROPIC_API_KEY"))
