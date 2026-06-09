"""Lectura de feeds RSS y filtrado por keywords."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import pandas as pd
import streamlit as st


@st.cache_data(ttl=600, show_spinner=False)
def fetch_feed(url: str, nombre: str) -> pd.DataFrame:
    """Trae items de un feed RSS. Devuelve DF vacío si falla."""
    try:
        parsed = feedparser.parse(
            url, request_headers={"User-Agent": "Mozilla/5.0 WarMonitor/1.0"}
        )
        items = parsed.entries
    except Exception:
        return pd.DataFrame()

    rows = []
    for e in items:
        # fecha
        ts = None
        for attr in ("published_parsed", "updated_parsed"):
            v = getattr(e, attr, None) or e.get(attr) if hasattr(e, "get") else None
            if v:
                try:
                    ts = datetime(*v[:6], tzinfo=timezone.utc)
                    break
                except Exception:
                    pass
        if ts is None:
            ts = datetime.now(timezone.utc)

        url_item = getattr(e, "link", "") or ""
        dominio = urlparse(url_item).netloc.lower().lstrip("www.") if url_item else ""

        rows.append(
            {
                "fecha": ts,
                "titulo": (getattr(e, "title", "") or "").strip(),
                "resumen": (getattr(e, "summary", "") or "").strip(),
                "url": url_item,
                "dominio": dominio,
                "fuente": nombre,
                "tipo_fuente": "RSS",
            }
        )
    return pd.DataFrame(rows)


def fetch_todos(feeds_cfg: list[dict]) -> pd.DataFrame:
    """Concatena todos los feeds activos del config."""
    dfs = []
    for f in feeds_cfg:
        if not f.get("activo", False):
            continue
        df = fetch_feed(f["url"], f["nombre"])
        if not df.empty:
            df["region"] = f.get("region", "")
            dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True).sort_values("fecha", ascending=False)


def filtrar_keywords(df: pd.DataFrame, keywords_cfg: dict) -> pd.DataFrame:
    """Agrega columnas `categorias` (lista) y `es_ataque_refineria` (bool).

    Solo retorna items que matchean al menos una categoría.
    """
    if df.empty:
        return df

    df = df.copy()
    texto = (df["titulo"].fillna("") + " " + df["resumen"].fillna("")).str.lower()

    cats_por_item = [[] for _ in range(len(df))]
    es_ataque = [False] * len(df)
    es_pirateria = [False] * len(df)
    peso_max = [0.0] * len(df)

    for cat, conf in keywords_cfg.items():
        terminos = conf.get("terminos", [])
        peso = conf.get("peso", 0.5)
        if not terminos:
            continue
        pattern = "|".join(t.lower() for t in terminos)
        mask = texto.str.contains(pattern, na=False, regex=True)
        for idx in df.index[mask]:
            pos = df.index.get_loc(idx)
            cats_por_item[pos].append(cat)
            if peso > peso_max[pos]:
                peso_max[pos] = peso
            if cat == "ataques_a_refinerias":
                es_ataque[pos] = True
            elif cat == "pirateria":
                es_pirateria[pos] = True

    df["categorias"] = cats_por_item
    df["es_ataque_refineria"] = es_ataque
    df["es_pirateria"] = es_pirateria
    df["peso_relevancia"] = peso_max
    df = df[df["categorias"].apply(lambda c: len(c) > 0)].copy()
    return df.reset_index(drop=True)


def estado_feeds(feeds_cfg: list[dict]) -> list[dict]:
    """Devuelve lista de feeds con su estado actual (para health panel)."""
    out = []
    for f in feeds_cfg:
        if not f.get("activo", False):
            out.append({"nombre": f["nombre"], "estado": "stale", "msg": "deshabilitado"})
            continue
        df = fetch_feed(f["url"], f["nombre"])
        if df.empty:
            out.append({"nombre": f["nombre"], "estado": "down", "msg": "sin items"})
        else:
            ult = df["fecha"].max()
            out.append({"nombre": f["nombre"], "estado": "ok", "ult_fecha": ult})
    return out
