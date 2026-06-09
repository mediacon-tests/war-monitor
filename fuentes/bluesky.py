"""Bluesky AppView público — sin auth, sin app password."""
from __future__ import annotations
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from atproto import Client


@st.cache_resource(show_spinner=False)
def _cliente() -> Client:
    """Cliente sobre el AppView público. No requiere login."""
    return Client(base_url="https://public.api.bsky.app")


@st.cache_data(ttl=300, show_spinner=False)
def fetch_posts_cuenta(handle: str, limit: int = 50) -> pd.DataFrame:
    """Trae posts recientes de una cuenta. Devuelve DF vacío si falla."""
    try:
        c = _cliente()
        res = c.get_author_feed(actor=handle, limit=limit, filter="posts_no_replies")
    except Exception:
        return pd.DataFrame()

    rows = []
    for v in res.feed:
        # excluir reposts (tienen v.reason)
        if getattr(v, "reason", None) is not None:
            continue
        p = v.post
        try:
            creado_en = datetime.fromisoformat(p.record.created_at.replace("Z", "+00:00"))
        except Exception:
            try:
                creado_en = datetime.fromisoformat(p.indexed_at.replace("Z", "+00:00"))
            except Exception:
                creado_en = datetime.now(timezone.utc)

        idiomas = getattr(p.record, "langs", None) or ["en"]

        # rkey para construir URL al post
        rkey = p.uri.rsplit("/", 1)[-1] if p.uri else ""

        rows.append(
            {
                "uri": p.uri,
                "handle": p.author.handle,
                "nombre_display": p.author.display_name or p.author.handle,
                "texto": p.record.text or "",
                "creado_en": creado_en,
                "likes": p.like_count or 0,
                "reposts": p.repost_count or 0,
                "replies": p.reply_count or 0,
                "idioma": idiomas[0] if idiomas else "en",
                "url_post": f"https://bsky.app/profile/{p.author.handle}/post/{rkey}",
            }
        )
    return pd.DataFrame(rows)


def fetch_todas_cuentas(cuentas_cfg: dict, limit_por_cuenta: int = 30) -> pd.DataFrame:
    """Itera por buckets, filtra `activo: true`, agrega `bucket` y `peso`."""
    dfs = []
    for bucket, cuentas in cuentas_cfg.items():
        if not isinstance(cuentas, list):
            continue
        for c in cuentas:
            if not c.get("activo", False):
                continue
            df = fetch_posts_cuenta(c["handle"], limit=limit_por_cuenta)
            if df.empty:
                continue
            df = df.copy()
            df["bucket"] = bucket
            df["peso"] = c.get("peso", 0.5)
            df["nombre_cuenta"] = c.get("nombre", c["handle"])
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()
    out = pd.concat(dfs, ignore_index=True).sort_values("creado_en", ascending=False)
    return out.reset_index(drop=True)


def filtrar_relevantes(df: pd.DataFrame, keywords_cfg: dict) -> pd.DataFrame:
    """Mantiene solo posts cuyo texto matchea al menos una keyword del config.

    Cuentas de medios generalistas (NYT, Guardian, etc.) postean de todo. Para que
    el sentiment sea sobre el conflicto y no sobre deportes/cultura, filtramos por
    keywords (case-insensitive, OR entre todos los buckets de keywords_cfg).
    """
    if df.empty or "texto" not in df.columns:
        return df
    todos_terminos: list[str] = []
    for bucket, conf in keywords_cfg.items():
        terminos = conf.get("terminos", []) if isinstance(conf, dict) else []
        todos_terminos.extend(t.lower() for t in terminos)
    if not todos_terminos:
        return df
    pattern = "|".join(t for t in todos_terminos)
    texto_lower = df["texto"].fillna("").str.lower()
    mask = texto_lower.str.contains(pattern, na=False, regex=True)
    return df[mask].reset_index(drop=True)


def cuentas_caidas(cuentas_cfg: dict) -> list[str]:
    """Lista de handles que están activos pero no devolvieron posts."""
    caidos = []
    for bucket, cuentas in cuentas_cfg.items():
        if not isinstance(cuentas, list):
            continue
        for c in cuentas:
            if not c.get("activo", False):
                continue
            df = fetch_posts_cuenta(c["handle"], limit=1)
            if df.empty:
                caidos.append(c["handle"])
    return caidos
