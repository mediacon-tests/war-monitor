"""Sentiment scoring. VADER si está disponible, lexicon casero como fallback."""
from __future__ import annotations
import re

import pandas as pd
import streamlit as st

from utiles.config import cargar

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    _VADER_OK = True
except Exception:
    _VADER_OK = False


@st.cache_resource(show_spinner=False)
def _analyzer():
    if _VADER_OK:
        return SentimentIntensityAnalyzer()
    return None


@st.cache_resource(show_spinner=False)
def _lexicon():
    cfg = cargar("lexicon_sentiment.yaml")
    flat = {}
    for grupo, palabras in cfg.items():
        if isinstance(palabras, dict):
            flat.update({k.lower(): float(v) for k, v in palabras.items()})
    return flat


def score_texto(texto: str) -> float:
    """Devuelve score [-1, 1] del texto. 0 si vacío / sin señal."""
    if not texto:
        return 0.0
    if _VADER_OK:
        a = _analyzer()
        return float(a.polarity_scores(texto)["compound"])
    # fallback lexicon
    lex = _lexicon()
    palabras = re.findall(r"[a-zA-Z']+", texto.lower())
    if not palabras:
        return 0.0
    suma = sum(lex.get(p, 0.0) for p in palabras)
    score = suma / max(len(palabras), 10)
    return max(-1.0, min(1.0, score))


def aplicar_sentiment(
    df: pd.DataFrame, columna_texto: str = "texto", solo_ingles: bool = True
) -> pd.DataFrame:
    """Calcula sentiment. Si `solo_ingles`, marca posts en otros idiomas con score=NaN.

    VADER fue entrenado en inglés; en otros idiomas devuelve ~0 silencioso, lo cual
    sesga el score agregado al neutro. Filtrar es preferible a contaminar.
    """
    if df.empty or columna_texto not in df.columns:
        return df
    df = df.copy()
    if solo_ingles and "idioma" in df.columns:
        mask = df["idioma"].fillna("en").str.lower().str.startswith("en")
        df["score"] = float("nan")
        df.loc[mask, "score"] = df.loc[mask, columna_texto].astype(str).apply(score_texto)
    else:
        df["score"] = df[columna_texto].astype(str).apply(score_texto)
    return df


def agregar_ponderado(
    df: pd.DataFrame, ventana: str = "1h", columna_ts: str = "creado_en"
) -> pd.DataFrame:
    """Agrega score ponderado por `peso` resampleado por `ventana`."""
    if df.empty or "score" not in df.columns:
        return pd.DataFrame()

    df = df.dropna(subset=[columna_ts]).copy()
    df[columna_ts] = pd.to_datetime(df[columna_ts], utc=True)
    df = df.set_index(columna_ts)

    if "peso" not in df.columns:
        df["peso"] = 1.0

    def agg(grupo):
        if grupo.empty or grupo["peso"].sum() == 0:
            return pd.Series({"score_pond": 0.0, "n_posts": 0, "n_cuentas": 0})
        return pd.Series(
            {
                "score_pond": (grupo["score"] * grupo["peso"]).sum() / grupo["peso"].sum(),
                "n_posts": len(grupo),
                "n_cuentas": grupo["handle"].nunique() if "handle" in grupo.columns else 0,
            }
        )

    res = df.resample(ventana).apply(agg)
    if isinstance(res, pd.DataFrame) and "score_pond" not in res.columns:
        # resample con apply puede no devolver columnas si todo fue vacío
        return pd.DataFrame()
    return res.reset_index()


def score_global(df: pd.DataFrame, ventana_horas: int = 24) -> dict:
    """Score ponderado global de las últimas N horas, agregación en dos pasos.

    Paso 1: score promedio por handle (cada cuenta cuenta una vez, sin importar verbosidad).
    Paso 2: promedio ponderado de los scores por handle, usando el peso de la cuenta.

    Esto evita que una cuenta verbosa domine el agregado.
    """
    if df.empty or "score" not in df.columns or "creado_en" not in df.columns:
        return {"score": 0.0, "n_posts": 0, "n_cuentas": 0, "n_descartados_lang": 0}
    desde = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=ventana_horas)
    sub = df[df["creado_en"] >= desde]
    if sub.empty:
        return {"score": 0.0, "n_posts": 0, "n_cuentas": 0, "n_descartados_lang": 0}

    n_descartados = int(sub["score"].isna().sum())
    sub_valido = sub.dropna(subset=["score"]).copy()

    if sub_valido.empty or "peso" not in sub_valido.columns or sub_valido["peso"].sum() == 0:
        return {
            "score": 0.0,
            "n_posts": int(len(sub)),
            "n_cuentas": int(sub["handle"].nunique()) if "handle" in sub.columns else 0,
            "n_descartados_lang": n_descartados,
        }

    # Paso 1: media por handle (incluye peso, que es constante por handle)
    por_handle = (
        sub_valido.groupby("handle")
        .agg(score_handle=("score", "mean"), peso_handle=("peso", "first"))
        .reset_index()
    )
    if por_handle["peso_handle"].sum() == 0:
        score = float(por_handle["score_handle"].mean())
    else:
        score = float(
            (por_handle["score_handle"] * por_handle["peso_handle"]).sum()
            / por_handle["peso_handle"].sum()
        )

    return {
        "score": score,
        "n_posts": int(len(sub_valido)),
        "n_cuentas": int(por_handle["handle"].nunique()),
        "n_descartados_lang": n_descartados,
    }
