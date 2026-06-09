"""Inventarios de gas natural / GNL — USA EIA live + curados para el resto.

Fuentes:
1. EIA API v2 (NW2_EPG0_SWO_R48_BCF): USA working gas en underground storage,
   semanal, Bcf → conversion a BCM.
2. EU (AGSI+): requeriría API key gratuita de GIE; mientras tanto, puntos
   curados de su dashboard público (gas storage fill mensual).
3. Japón: METI weekly LNG inventories at power utilities, en MT → conversión
   a BCM (~1.38 BCM por MT LNG). Puntos curados.
4. China: NDRC / IEA estimates de capacidad y nivel. Puntos curados.

A diferencia del SPR de crudo, el storage de gas es altamente seasonal
(inyección verano, draw invierno), no estratégico en el mismo sentido.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from utiles.config import DIR_CACHE
from utiles.secretos import obtener as obtener_secret


EIA_GAS_API = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
EIA_GAS_CACHE = DIR_CACHE / "eia_gas_usa.csv"
EIA_GAS_CACHE_HORAS = 6
BCF_POR_BCM = 35.3   # 1 BCM = 35.3 Bcf


def _leer_cache_gas() -> pd.DataFrame:
    if not EIA_GAS_CACHE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(EIA_GAS_CACHE)
        df["fecha"] = pd.to_datetime(df["fecha"], utc=True, errors="coerce")
        return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _cache_gas_fresco() -> bool:
    if not EIA_GAS_CACHE.exists():
        return False
    edad_h = (datetime.now(timezone.utc).timestamp() - EIA_GAS_CACHE.stat().st_mtime) / 3600
    return edad_h < EIA_GAS_CACHE_HORAS


@st.cache_data(ttl=3600, show_spinner=False)
def gas_usa_semanal(dias: int = 900) -> pd.DataFrame:
    """USA working gas underground semanal vía EIA API + cache a disco.

    Devuelve DF con `fecha` y `bcm` (billion cubic meters).
    """
    DIR_CACHE.mkdir(exist_ok=True)

    if _cache_gas_fresco():
        df_cache = _leer_cache_gas()
        if not df_cache.empty:
            return df_cache

    api_key = obtener_secret("EIA_API_KEY") or "DEMO_KEY"
    inicio = (datetime.now(timezone.utc) - pd.Timedelta(days=dias)).strftime("%Y-%m-%d")
    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": "NW2_EPG0_SWO_R48_BCF",
        "start": inicio,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }
    try:
        r = requests.get(EIA_GAS_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json().get("response", {}).get("data", [])
        if not data:
            raise RuntimeError("EIA gas response empty")
        df = pd.DataFrame(data)
        df["fecha"] = pd.to_datetime(df["period"], utc=True, errors="coerce")
        df["bcm"] = pd.to_numeric(df["value"], errors="coerce") / BCF_POR_BCM
        df = df[["fecha", "bcm"]].dropna().sort_values("fecha").reset_index(drop=True)
        df.to_csv(EIA_GAS_CACHE, index=False)
        return df
    except Exception:
        return _leer_cache_gas()


def series_historicas_gas(cfg: dict, desde: str | None = None) -> dict[str, pd.DataFrame]:
    """Series temporales de inventario de gas/LNG por región.

    - USA: live EIA NW2 semanal.
    - EU, Japón, China: puntos curados del config.
    """
    series: dict[str, pd.DataFrame] = {}

    df_us = gas_usa_semanal(dias=900)
    if not df_us.empty:
        series["USA"] = df_us[["fecha", "bcm"]]

    for nombre, conf in (cfg.get("series") or {}).items():
        if nombre == "USA" and "USA" in series:
            continue
        puntos = conf.get("puntos", [])
        if not puntos:
            continue
        df = pd.DataFrame(puntos)
        df["fecha"] = pd.to_datetime(df["fecha"], utc=True, errors="coerce")
        df["bcm"] = pd.to_numeric(df["bcm"], errors="coerce")
        df = df.dropna().sort_values("fecha").reset_index(drop=True)
        if not df.empty:
            series[nombre] = df

    if desde:
        try:
            corte = pd.Timestamp(desde, tz="UTC")
            corte_extendido = corte - pd.Timedelta(days=90)
            series = {
                k: v[v["fecha"] >= corte_extendido].reset_index(drop=True)
                for k, v in series.items()
            }
        except Exception:
            pass
    return series


def snapshot_global_gas(cfg: dict, series: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Snapshot actual de inventarios de gas con consumo y días de cobertura."""
    paises = cfg.get("paises", [])
    rows = []
    for p in paises:
        rows.append({
            "pais": p["nombre"],
            "bcm": float(p["bcm"]),
            "consumo_diario_bcm": float(p.get("consumo_diario_bcm", 0) or 0),
            "capacidad_bcm": float(p.get("capacidad_bcm", 0) or 0),
            "tipo": p.get("tipo", "underground"),
            "fecha": p.get("fecha", ""),
            "nota": p.get("nota", ""),
        })
    df = pd.DataFrame(rows)
    # Sobrescribir USA con dato live EIA
    df_us = gas_usa_semanal(dias=30)
    if not df_us.empty:
        ult = df_us.iloc[-1]
        mask = df["pais"] == "USA"
        if mask.any():
            df.loc[mask, "bcm"] = float(ult["bcm"])
            df.loc[mask, "fecha"] = ult["fecha"].strftime("%Y-%m-%d")
    # Días de cobertura = inventario / consumo diario
    df["dias_cobertura"] = df.apply(
        lambda r: r["bcm"] / r["consumo_diario_bcm"] if r["consumo_diario_bcm"] > 0 else None,
        axis=1,
    )
    # % de capacidad usada (si está disponible)
    df["pct_capacidad"] = df.apply(
        lambda r: r["bcm"] / r["capacidad_bcm"] * 100 if r["capacidad_bcm"] > 0 else None,
        axis=1,
    )
    return df


def ultima_fecha_gas(series: dict[str, pd.DataFrame]) -> str:
    fechas = []
    for k in ("EU", "Japón", "China"):
        df = series.get(k)
        if df is not None and not df.empty:
            fechas.append(df["fecha"].max())
    return max(fechas).strftime("%Y-%m") if fechas else ""
