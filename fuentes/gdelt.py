"""GDELT DOC 2.0 API — sin auth, ~3 meses de ventana, lento."""
from __future__ import annotations
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

URL_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT = 45  # GDELT es lento; setear holgado


def construir_query(buckets: list[str], keywords_cfg: dict, max_terminos: int = 12) -> str:
    """Construye query OR concatenando keywords de los buckets seleccionados.

    GDELT acepta queries largas pero devuelve 0 resultados si superan cierta complejidad
    no documentada. Se limita a `max_terminos` totales repartiendo entre buckets.
    """
    if not buckets:
        return ""
    terminos_por_bucket = max(1, max_terminos // len(buckets))
    todos: list[str] = []
    for b in buckets:
        terminos = keywords_cfg.get(b, {}).get("terminos", [])[:terminos_por_bucket]
        for t in terminos:
            t = t.strip()
            if " " in t or "-" in t:
                todos.append(f'"{t}"')
            else:
                todos.append(t)
    if not todos:
        return ""
    if len(todos) == 1:
        return todos[0]
    return "(" + " OR ".join(todos) + ")"


@st.cache_data(ttl=900, show_spinner=False)
def buscar_articulos(query: str, timespan: str = "3d", max_records: int = 250) -> pd.DataFrame:
    """ArtList: lista de artículos. Sort = DateDesc."""
    if not query:
        return pd.DataFrame()
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "timespan": timespan,
        "maxrecords": min(max_records, 250),
        "sort": "DateDesc",
    }
    try:
        r = requests.get(
            URL_GDELT,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return pd.DataFrame()

    if r.status_code != 200:
        return pd.DataFrame()
    if "json" not in r.headers.get("content-type", ""):
        return pd.DataFrame()

    try:
        data = r.json()
    except ValueError:
        return pd.DataFrame()

    arts = data.get("articles", [])
    if not arts:
        return pd.DataFrame()

    df = pd.DataFrame(arts)
    if "seendate" in df.columns:
        df["fecha"] = pd.to_datetime(df["seendate"], format="%Y%m%dT%H%M%SZ", utc=True, errors="coerce")
    else:
        df["fecha"] = pd.NaT
    df["fuente"] = "GDELT"
    df["tipo_fuente"] = "GDELT"
    df["resumen"] = ""
    df = df.rename(columns={"title": "titulo", "domain": "dominio"})
    cols = ["fecha", "titulo", "url", "dominio", "language", "sourcecountry", "fuente", "tipo_fuente", "resumen"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].sort_values("fecha", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def timeline_volumen(query: str, timespan: str = "30d") -> pd.DataFrame:
    """TimelineVolRaw: serie temporal del volumen de artículos."""
    if not query:
        return pd.DataFrame()
    params = {
        "query": query,
        "mode": "TimelineVolRaw",
        "format": "json",
        "timespan": timespan,
    }
    try:
        r = requests.get(
            URL_GDELT,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return pd.DataFrame()
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        return pd.DataFrame()
    try:
        data = r.json()
    except ValueError:
        return pd.DataFrame()

    series = data.get("timeline", [])
    rows = []
    for s in series:
        nombre = s.get("series", "")
        for d in s.get("data", []):
            try:
                ts = datetime.strptime(d["date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                rows.append({"fecha": ts, "volumen": d["value"], "serie": nombre})
            except Exception:
                continue
    return pd.DataFrame(rows)
