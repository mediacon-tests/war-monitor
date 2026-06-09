"""Precios de mercado vía yfinance + series derivadas (spreads, cracks)."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf
import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def serie_historica(ticker: str, dias: int = 180) -> pd.DataFrame:
    """Cierre histórico para un ticker. Forza tz UTC en `fecha`."""
    fin = datetime.now(timezone.utc)
    inicio = fin - timedelta(days=dias)
    try:
        df = yf.download(
            ticker,
            start=inicio.strftime("%Y-%m-%d"),
            end=fin.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={"Date": "fecha", "Close": "cierre"})
    df = df[["fecha", "cierre"]].dropna()
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True, errors="coerce")
    return df.dropna(subset=["fecha"]).reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def series_batch(tickers: tuple[str, ...], dias: int = 180) -> pd.DataFrame:
    """Trae múltiples tickers en una sola request. Devuelve DF wide: fecha + un col por ticker."""
    if not tickers:
        return pd.DataFrame()
    fin = datetime.now(timezone.utc)
    inicio = fin - timedelta(days=dias)
    try:
        df = yf.download(
            list(tickers),
            start=inicio.strftime("%Y-%m-%d"),
            end=fin.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
            group_by="column",
        )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df

    # Para single ticker yfinance NO usa MultiIndex; para múltiples sí.
    if isinstance(df.columns, pd.MultiIndex):
        # Tomar solo Close
        if "Close" in df.columns.get_level_values(0):
            df = df["Close"]
    else:
        df = df[["Close"]].rename(columns={"Close": tickers[0]})

    df.index.name = "fecha"
    return df.reset_index()


@st.cache_data(ttl=60, show_spinner=False)
def cotizacion_actual(ticker: str) -> dict | None:
    """Cierre + previo + variación %.

    Valida la barra del día contra `fast_info` (open/high/low). En futuros continuos
    (BZ=F, CL=F) el día de rollover yfinance mezcla contratos y devuelve barras
    inconsistentes (ej. high < open). Cuando se detecta corrupción, cae al último
    cierre válido del histórico — el precio queda 1 día atrasado pero correcto.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        ultimo = float(info["last_price"])
        # regularMarketPreviousClose suele ser más fresco que previousClose
        anterior_raw = info.get("regularMarketPreviousClose") or info.get("previous_close")
        anterior = float(anterior_raw) if anterior_raw else 0.0

        # Validación anti-rollover: si la barra del día es inconsistente
        # (high < open, last fuera del rango low/high), pull histórico y usar
        # el último cierre limpio.
        try:
            o = float(info.get("open", 0) or 0)
            h = float(info.get("dayHigh", 0) or 0)
            low = float(info.get("dayLow", 0) or 0)
            barra_corrupta = (
                (h > 0 and o > 0 and h < o)
                or (h > 0 and low > 0 and h < low)
                or (h > 0 and ultimo > h * 1.001)
                or (low > 0 and ultimo < low * 0.999)
            )
        except (TypeError, ValueError):
            barra_corrupta = False

        if barra_corrupta:
            hist = t.history(period="10d")
            # Filtrar barras donde H >= O y H >= L (consistentes)
            valid = hist[
                (hist["High"] >= hist["Open"])
                & (hist["High"] >= hist["Low"])
                & (hist["Close"] > 0)
            ]
            if len(valid) >= 2:
                ultimo = float(valid["Close"].iloc[-1])
                anterior = float(valid["Close"].iloc[-2])

        variacion = (ultimo - anterior) / anterior * 100 if anterior else 0.0
        return {
            "ticker": ticker,
            "precio": ultimo,
            "variacion_pct": variacion,
            "previo": anterior,
        }
    except Exception:
        return None


def calcular_derivado(df_wide: pd.DataFrame, formula_dict: dict) -> pd.DataFrame:
    """Aplica una fórmula a un DF wide.

    Reemplaza nombres limpios (sin =F, sin ^) en la fórmula por la columna correspondiente.
    Usa `eval` con builtins desactivados y reemplazo por word-boundary regex para evitar
    sustituciones parciales (CL vs CLO).
    """
    import re

    if df_wide.empty:
        return pd.DataFrame()
    formula = formula_dict.get("formula", "")
    operandos = formula_dict.get("operandos", [])
    if not formula or not operandos:
        return pd.DataFrame()

    expr = formula
    # Ordenar de más largo a más corto para evitar reemplazos parciales
    for op in sorted(operandos, key=len, reverse=True):
        clean = op.replace("=F", "").replace("^", "")
        if clean in df_wide.columns:
            col = clean
        elif op in df_wide.columns:
            col = op
        else:
            return pd.DataFrame()
        # word-boundary garantiza que CL no matchea CLO
        expr = re.sub(rf"\b{re.escape(clean)}\b", f'_d["{col}"]', expr)

    try:
        # Sandbox: builtins vacíos, solo el DataFrame disponible
        serie = eval(expr, {"__builtins__": {}}, {"_d": df_wide})  # noqa: S307
    except Exception:
        return pd.DataFrame()

    out = pd.DataFrame({"fecha": df_wide["fecha"], "valor": serie}).dropna()
    return out


def serie_normalizada(df: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """Normaliza una serie cierre a base 100 desde el primer punto."""
    if df.empty or "cierre" not in df.columns:
        return df
    primer = df["cierre"].iloc[0]
    if primer == 0 or pd.isna(primer):
        return df
    df = df.copy()
    df["normalizado"] = df["cierre"] / primer * base
    return df


def hormuz_stress_index(df_ovx, df_brent, df_oro, df_vix, df_move) -> pd.DataFrame:
    """HSI compuesto de z-scores rolling 90d.

    Para series no estacionarias (Brent, Oro), usa el z-score del retorno log 5d en
    lugar del nivel — evita falsos positivos por shifts de régimen estructural.
    Para vol indices (^OVX, ^VIX, ^MOVE), usa z-score del nivel (son estacionarios).
    `min_periods=60` garantiza ventana madura antes de emitir z-score válido.

    Score > +1.5 = mercado pricing event; > +2.0 = stress agudo.
    """
    z_dfs = []
    series_map = {
        "OVX": (df_ovx, "nivel"),
        "BRENT": (df_brent, "retorno"),
        "ORO": (df_oro, "retorno"),
        "VIX": (df_vix, "nivel"),
        "MOVE": (df_move, "nivel"),
    }
    for nombre, (df, modo) in series_map.items():
        if df is None or df.empty or len(df) < 60:
            continue
        df = df.copy().sort_values("fecha")
        if modo == "retorno":
            import numpy as np
            df["x"] = np.log(df["cierre"] / df["cierre"].shift(5))
        else:
            df["x"] = df["cierre"]
        df["mu"] = df["x"].rolling(90, min_periods=60).mean()
        df["sigma"] = df["x"].rolling(90, min_periods=60).std()
        df["sigma"] = df["sigma"].replace(0, pd.NA)
        df[f"z_{nombre}"] = (df["x"] - df["mu"]) / df["sigma"]
        z_dfs.append(df[["fecha", f"z_{nombre}"]])

    if not z_dfs:
        return pd.DataFrame()

    out = z_dfs[0]
    for d in z_dfs[1:]:
        out = out.merge(d, on="fecha", how="outer")
    z_cols = [c for c in out.columns if c.startswith("z_")]
    out["HSI"] = out[z_cols].mean(axis=1, skipna=True)
    out["n_componentes"] = out[z_cols].notna().sum(axis=1)
    return out.sort_values("fecha")
