from functools import lru_cache
from pathlib import Path
import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"
DIR_CACHE = RAIZ / "datos_cache"


@lru_cache(maxsize=32)
def cargar(nombre: str) -> dict:
    ruta = DIR_CONFIG / nombre
    try:
        with ruta.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError:
        return {}
