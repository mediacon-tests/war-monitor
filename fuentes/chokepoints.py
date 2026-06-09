"""IMF PortWatch — tránsitos diarios por chokepoints (sin auth).

Endpoint:
  https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/
    Daily_Chokepoints_Data/FeatureServer/0/query

Datos actualizados los martes ~9am ET. Lag típico de ~5-7 días.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import streamlit as st

URL_PORTWATCH = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
TIMEOUT = 30
PAGE_SIZE = 1000  # max del FeatureServer


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_transitos(portids: list[str], dias: int = 365) -> pd.DataFrame:
    """Trae tránsitos diarios de los portids dados, últimos N días."""
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    desde_str = desde.strftime("%Y-%m-%d %H:%M:%S")
    portids_sql = ",".join(f"'{p}'" for p in portids)
    where = f"portid IN ({portids_sql}) AND date >= TIMESTAMP '{desde_str}'"

    out_fields = (
        "date,portid,portname,n_tanker,n_total,capacity_tanker,capacity"
    )

    todos = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "orderByFields": "date ASC",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "json",
        }
        try:
            r = requests.get(URL_PORTWATCH, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        feats = data.get("features", [])
        if not feats:
            break
        todos.extend(feats)
        if len(feats) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not todos:
        return pd.DataFrame()

    rows = [f["attributes"] for f in todos]
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    df = df.drop(columns=["date"], errors="ignore")
    df["tanker_share"] = df["n_tanker"] / df["n_total"].replace(0, pd.NA)
    return df.sort_values(["portid", "fecha"]).reset_index(drop=True)


def resumen_vs_baseline(
    df: pd.DataFrame, ventana_actual: int = 7, ventana_baseline: int = 90
) -> pd.DataFrame:
    """Compara la mediana de tanqueros últimos N días vs baseline histórico.

    Usa **mediana + MAD** (robusto a outliers) y **mismo día de semana** para
    el baseline (los tránsitos tienen estacionalidad semanal fuerte).
    Devuelve también `lag_dias` para que la UI advierta sobre la antigüedad de la data.
    """
    if df.empty:
        return pd.DataFrame()

    import numpy as np

    out = []
    ahora = pd.Timestamp.now(tz="UTC")
    for portid, g in df.groupby("portid"):
        g = g.sort_values("fecha").copy()
        g["dow"] = g["fecha"].dt.dayofweek
        ult_fecha = g["fecha"].max()
        lag_dias = (ahora.normalize() - ult_fecha.normalize()).days

        actual_g = g.tail(ventana_actual)
        actual = actual_g["n_tanker"].median()

        # Baseline = mismos días-de-semana de los últimos `ventana_baseline` días
        base_g = g[g["fecha"] < (ult_fecha - pd.Timedelta(days=ventana_actual))].tail(
            ventana_baseline * 2
        )
        # Estacionalidad semanal: matchear DOW de las muestras actuales
        dows_actuales = actual_g["dow"].unique()
        base_dow = base_g[base_g["dow"].isin(dows_actuales)]

        if len(base_dow) >= 6:
            mediana_b = base_dow["n_tanker"].median()
            mad = np.median(np.abs(base_dow["n_tanker"] - mediana_b))
            mad = mad if mad > 0 else base_dow["n_tanker"].std()  # fallback
            # 0.6745 ≈ scaling para que MAD sea consistente con sigma normal
            score = 0.6745 * (actual - mediana_b) / mad if mad else float("nan")
        else:
            mediana_b = base_g["n_tanker"].median() if len(base_g) > 0 else float("nan")
            mad = base_g["n_tanker"].std() if len(base_g) > 5 else float("nan")
            score = (actual - mediana_b) / mad if mad and mad > 0 else float("nan")

        desvio_pct = (
            (actual - mediana_b) / mediana_b * 100
            if pd.notna(mediana_b) and mediana_b > 0
            else float("nan")
        )

        out.append(
            {
                "portid": portid,
                "portname": g["portname"].iloc[-1],
                "actual": actual,
                "baseline": mediana_b,
                "desvio_pct": desvio_pct,
                "z_score": score,
                "ult_fecha": ult_fecha,
                "lag_dias": lag_dias,
            }
        )
    return pd.DataFrame(out)


def calcular_estado(z: float | None) -> str:
    """Clasifica el desvío en ok/warn/down. Para alertas visuales."""
    if z is None or pd.isna(z):
        return "stale"
    if z <= -2.0:
        return "down"
    if z <= -1.0:
        return "warn"
    return "ok"
