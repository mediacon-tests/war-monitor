"""Lectura unificada de secrets.

Prioridad: (1) st.secrets (cargado desde .streamlit/secrets.toml local — no commiteado,
en .gitignore), (2) variables de entorno del sistema. Devuelve "" si no existe.
"""
import os


def obtener(clave: str) -> str:
    # 1. st.secrets (Streamlit)
    try:
        import streamlit as st
        try:
            valor = st.secrets.get(clave, "")
        except Exception:
            valor = ""
        if valor:
            return str(valor).strip()
    except Exception:
        pass
    # 2. env var
    return os.environ.get(clave, "").strip()
