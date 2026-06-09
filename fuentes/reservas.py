"""Reservas / inventarios de crudo — USA SPR semanal + JODI mensual + China estimado.

Fuentes:
1. EIA API v2 (WCSSTUS1): USA SPR semanal, granularidad fina pero solo gobierno.
2. JODI Oil World Database: stocks de crudo TOTAL (comercial + estratégico)
   mensual por país. CSVs anuales gratuitos, descarga directa, no requiere key.
   Lag típico ~2 meses. URL pattern:
     https://www.jodidata.org/_resources/files/downloads/oil-data/annual-csv/primary/{year}.csv
3. China: no reporta a JODI. Estimación EIA Today In Energy en config/reservas.yaml
   (puntos sparse, manual ~1-2 veces/año).

Métrica unificada para el chart histórico: closing stock level (CLOSTLV) en miles
de barriles → convertido a millones para el plot.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from utiles.config import DIR_CACHE
from utiles.secretos import obtener as obtener_secret


EIA_API = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
JODI_BASE = "https://www.jodidata.org/_resources/files/downloads/oil-data/annual-csv/primary"
JODI_CACHE_DIAS = 7  # re-bajar CSV si tiene >7d (JODI publica el 20 de cada mes)

# Miembros OECD Europa (códigos ISO 2 letras como aparecen en JODI)
OECD_EUROPA_CODIGOS = {
    "AT","BE","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT","LV",
    "LT","LU","NL","PL","PT","SK","SI","ES","SE","GB","NO","CH","IS","TR",
}


EIA_CACHE_PATH = DIR_CACHE / "eia_spr_usa.csv"
EIA_CACHE_HORAS = 6   # re-pegar EIA si el cache tiene >6h


def _leer_cache_eia() -> pd.DataFrame:
    """Lee SPR USA del cache en disco si existe."""
    if not EIA_CACHE_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(EIA_CACHE_PATH)
        df["fecha"] = pd.to_datetime(df["fecha"], utc=True, errors="coerce")
        return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _cache_eia_fresco() -> bool:
    if not EIA_CACHE_PATH.exists():
        return False
    edad_h = (datetime.now(timezone.utc).timestamp() - EIA_CACHE_PATH.stat().st_mtime) / 3600
    return edad_h < EIA_CACHE_HORAS


@st.cache_data(ttl=3600, show_spinner=False)
def spr_usa_semanal(dias: int = 730) -> pd.DataFrame:
    """SPR USA semanal vía EIA API + cache a disco (resiliente a rate limits).

    Si la API responde OK, persiste a disco. Si falla (429 rate limit, timeout,
    etc.), devuelve el último cache disponible. El cache se considera fresco
    durante EIA_CACHE_HORAS para evitar requests innecesarios.
    """
    DIR_CACHE.mkdir(exist_ok=True)

    # Si el cache es fresco, devolverlo sin llamar la API
    if _cache_eia_fresco():
        df_cache = _leer_cache_eia()
        if not df_cache.empty:
            return df_cache

    # Cache viejo o inexistente — intentar API
    api_key = obtener_secret("EIA_API_KEY") or "DEMO_KEY"
    inicio = (datetime.now(timezone.utc) - pd.Timedelta(days=dias)).strftime("%Y-%m-%d")
    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": "WCSSTUS1",
        "start": inicio,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }
    try:
        r = requests.get(EIA_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json().get("response", {}).get("data", [])
        if not data:
            raise RuntimeError("EIA response empty")
        df = pd.DataFrame(data)
        df["fecha"] = pd.to_datetime(df["period"], utc=True, errors="coerce")
        df["cierre"] = pd.to_numeric(df["value"], errors="coerce") / 1000.0
        df = df[["fecha", "cierre"]].dropna().sort_values("fecha").reset_index(drop=True)
        # Persistir a disco
        df.to_csv(EIA_CACHE_PATH, index=False)
        return df
    except Exception:
        # API falló — devolver cache de disco (aunque sea viejo)
        return _leer_cache_eia()


def snapshot_global(cfg: dict, series: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Snapshot comparativo del último dato disponible por país.

    Devuelve columnas: pais, mbbl, consumo_diario_mbbl, importaciones_netas_mbbl,
    dias_cobertura (= mbbl / importaciones_netas), tipo, fecha, fuente, nota.
    """
    paises = cfg.get("paises", [])
    fuente_default = cfg.get("fuente_principal", "EIA Today In Energy")
    fecha_default = cfg.get("fecha_snapshot", "")
    rows = []
    for p in paises:
        rows.append({
            "pais": p["nombre"],
            "mbbl": float(p["mbbl"]),
            "consumo_diario_mbbl": float(p.get("consumo_diario_mbbl", 0) or 0),
            "importaciones_netas_mbbl": float(p.get("importaciones_netas_mbbl", 0) or 0),
            "tipo": p.get("tipo", "gobierno"),
            "fuente": p.get("fuente", fuente_default),
            "fecha": p.get("fecha", fecha_default),
            "nota": p.get("nota", ""),
        })
    df = pd.DataFrame(rows)
    # Sobrescribir USA con el último dato live EIA
    df_us = spr_usa_semanal(dias=30)
    if not df_us.empty:
        ult = df_us.iloc[-1]
        mask = df["pais"] == "USA"
        if mask.any():
            df.loc[mask, "mbbl"] = float(ult["cierre"])
            df.loc[mask, "fecha"] = ult["fecha"].strftime("%Y-%m-%d")
            df.loc[mask, "fuente"] = "EIA WCSSTUS1 (live)"
    # Días de cobertura: SPR / net imports (estándar IEA). Si net imports ≤ 0, usar consumo.
    def _dias(row):
        denom = row["importaciones_netas_mbbl"] if row["importaciones_netas_mbbl"] > 0 else row["consumo_diario_mbbl"]
        return row["mbbl"] / denom if denom > 0 else None
    df["dias_cobertura"] = df.apply(_dias, axis=1)
    return df


def _jodi_csv_path(year: int) -> Path:
    DIR_CACHE.mkdir(exist_ok=True)
    return DIR_CACHE / f"jodi_primary_{year}.csv"


def _jodi_csv_url(year: int) -> str:
    # 2026 (año en curso) tiene URL especial; el resto usan {year}.csv
    actual = datetime.now(timezone.utc).year
    if year == actual:
        return f"{JODI_BASE}/primaryyear{year}.csv"
    return f"{JODI_BASE}/{year}.csv"


def _bajar_jodi(year: int) -> Path | None:
    """Descarga el CSV anual si no existe o está viejo. Devuelve path o None."""
    path = _jodi_csv_path(year)
    if path.exists():
        edad_dias = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 86400
        if edad_dias < JODI_CACHE_DIAS:
            return path
    try:
        r = requests.get(_jodi_csv_url(year), timeout=30)
        r.raise_for_status()
        path.write_bytes(r.content)
        return path
    except Exception:
        return path if path.exists() else None


@st.cache_data(ttl=86400, show_spinner=False)
def _jodi_stocks_crude(years: tuple[int, ...]) -> pd.DataFrame:
    """Concatena CSVs JODI y filtra a CRUDEOIL closing stocks por país (KBBL)."""
    frames = []
    for y in years:
        path = _bajar_jodi(y)
        if not path or not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        df = df[
            (df["ENERGY_PRODUCT"] == "CRUDEOIL")
            & (df["FLOW_BREAKDOWN"] == "CLOSTLV")
            & (df["UNIT_MEASURE"] == "KBBL")
        ].copy()
        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
        df = df.dropna(subset=["OBS_VALUE"])
        df = df[df["OBS_VALUE"] > 0]
        frames.append(df[["REF_AREA", "TIME_PERIOD", "OBS_VALUE"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["fecha"] = pd.to_datetime(out["TIME_PERIOD"] + "-15", utc=True, errors="coerce")
    out = out.dropna(subset=["fecha"]).sort_values("fecha")
    return out


def _jodi_pais(df_jodi: pd.DataFrame, codigo: str) -> pd.DataFrame:
    """Extrae serie de un país (KBBL → Mbbl)."""
    if df_jodi.empty:
        return pd.DataFrame()
    sub = df_jodi[df_jodi["REF_AREA"] == codigo].copy()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.groupby("fecha", as_index=False)["OBS_VALUE"].sum()
    sub["mbbl"] = sub["OBS_VALUE"] / 1000.0
    return sub[["fecha", "mbbl"]].reset_index(drop=True)


def _jodi_oecd_europa(df_jodi: pd.DataFrame) -> pd.DataFrame:
    """Suma stocks de todos los países OECD Europa con data ese mes."""
    if df_jodi.empty:
        return pd.DataFrame()
    sub = df_jodi[df_jodi["REF_AREA"].isin(OECD_EUROPA_CODIGOS)].copy()
    if sub.empty:
        return pd.DataFrame()
    agg = sub.groupby("fecha", as_index=False)["OBS_VALUE"].sum()
    agg["mbbl"] = agg["OBS_VALUE"] / 1000.0
    return agg[["fecha", "mbbl"]].reset_index(drop=True)


def series_historicas(cfg: dict, desde: str | None = None) -> dict[str, pd.DataFrame]:
    """Series temporales SPR (gobierno-controladas) por país.

    - USA: live EIA WCSSTUS1 semanal (SPR-only). Fallback: serie de fallback
      del config si la API falla y no hay cache.
    - Japón, OECD Europa, China: puntos curados de config (EIA Today In Energy
      + IEA OMR + releases discretos). Para China = total bajo control estatal.
    """
    series: dict[str, pd.DataFrame] = {}

    # USA: live EIA (con cache a disco resiliente a rate limits)
    df_us = spr_usa_semanal(dias=900)
    if not df_us.empty:
        series["USA"] = df_us[["fecha", "cierre"]].rename(columns={"cierre": "mbbl"})

    # Resto + fallback USA: puntos curados del config
    for nombre, conf in (cfg.get("series") or {}).items():
        if nombre == "USA" and "USA" in series:
            # Ya tenemos USA live, no sobrescribir con sparse
            continue
        puntos = conf.get("puntos", [])
        if not puntos:
            continue
        df = pd.DataFrame(puntos)
        df["fecha"] = pd.to_datetime(df["fecha"], utc=True, errors="coerce")
        df["mbbl"] = pd.to_numeric(df["mbbl"], errors="coerce")
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


def ultima_fecha_jodi(series: dict[str, pd.DataFrame]) -> str:
    """Devuelve la fecha del dato más reciente entre las series no-USA.

    (Mantiene el nombre histórico aunque ya no usa JODI; mide la freshness
    del snapshot de puntos curados.)
    """
    fechas = []
    for k in ("Japón", "OECD Europa", "China"):
        df = series.get(k)
        if df is not None and not df.empty:
            fechas.append(df["fecha"].max())
    return max(fechas).strftime("%Y-%m") if fechas else ""


def normalizar_a_base(series: dict[str, pd.DataFrame], fecha_base: str, base: float = 100.0) -> dict[str, pd.DataFrame]:
    """Normaliza cada serie a `base` en `fecha_base`.

    Toma el punto más cercano (forward o backward) a `fecha_base` como anchor.
    Devuelve dict con columna `indice` además de `mbbl`.
    """
    try:
        anchor = pd.Timestamp(fecha_base, tz="UTC")
    except Exception:
        return series
    out = {}
    for pais, df in series.items():
        if df.empty or "mbbl" not in df.columns:
            continue
        df = df.copy().sort_values("fecha").reset_index(drop=True)
        # punto más cercano a la fecha base
        idx_min = (df["fecha"] - anchor).abs().idxmin()
        valor_base = float(df.loc[idx_min, "mbbl"])
        if valor_base <= 0 or pd.isna(valor_base):
            continue
        df["indice"] = df["mbbl"] / valor_base * base
        out[pais] = df
    return out
