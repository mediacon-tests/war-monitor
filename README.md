# War Monitor

Dashboard "dogwatch" en tiempo (casi) real del conflicto Irán ↔ EE.UU. / Israel desde la óptica de mercados de energía. Streamlit + Python.

Cubre seis dimensiones en un solo dashboard minimalista:

1. **Mercados** — Brent / WTI / OVX / oro con HSI (Hormuz Stress Index) compuesto.
2. **Chokepoints** — tránsito diario de tanqueros por Hormuz, Suez y Bab el-Mandeb vs baseline robusto (mediana + MAD, misma DOW).
3. **Reservas estratégicas (SPR)** — USA / China / Japón / OECD Europa con trayectoria desde el inicio del conflicto + días de cobertura.
4. **Inventarios de gas / GNL** — USA / EU / China / Japón con storage y días de cobertura.
5. **Inteligencia abierta** — tape de RSS + GDELT 2.0 y sentiment de Bluesky vía Claude Haiku 4.5.
6. **Eventos críticos** — ataques a refinerías (72h) y pirateria marítima (7d) destacados.

Más un brief generado por IA y commodities sectoriales (destilados, petquím, fertilizantes, fletes, refinerías, LNG, defensa, macro) en un expander al final.

## Setup

```bash
git clone https://github.com/marianopmartin/war-monitor.git
cd war-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Secrets (opcional pero recomendado)

El dashboard funciona sin keys, pero algunos features (sentiment con Claude, EIA fresh) mejoran con keys propias.

```bash
cp .streamlit/secrets.toml.template .streamlit/secrets.toml
# Editar y agregar las keys disponibles
```

Variables soportadas:

| Variable | Para qué | Cómo obtenerla |
|----------|---------|----------------|
| `ANTHROPIC_API_KEY` | Sentiment geopolítico-energético + resumen IA (Haiku 4.5) | https://console.anthropic.com/ |
| `EIA_API_KEY` | SPR USA + gas USA con rate limit alto | https://api.eia.gov/key/ (free, instantáneo) |

Sin keys el dashboard cae a VADER (sentiment léxico) y `DEMO_KEY` de EIA (5 req/h).

### Correr

```bash
streamlit run app.py --server.port 8511
```

Abrir http://localhost:8511

## Stack

- **Streamlit** — UI single-file
- **Plotly** — gráficos
- **yfinance** — commodities + delayed quotes (15-20 min)
- **feedparser** — RSS
- **atproto** — Bluesky AppView público (no auth)
- **anthropic** — Claude Haiku 4.5 (sentiment + brief)
- **requests** — EIA API, JODI, GDELT, IMF PortWatch

## Estructura

```
war-monitor/
├── app.py                    # Dashboard single-file
├── fuentes/                  # Loaders por data source
│   ├── precios.py            # yfinance + HSI
│   ├── chokepoints.py        # IMF PortWatch ArcGIS
│   ├── reservas.py           # SPR USA EIA + curado no-US
│   ├── lng.py                # Gas EIA + curado no-US
│   ├── rss.py                # RSS feeds
│   ├── gdelt.py              # GDELT 2.0 DOC API
│   ├── bluesky.py            # Bluesky AppView
│   ├── sentiment.py          # VADER fallback
│   ├── sentiment_claude.py   # Claude geopolítico
│   └── resumen_ai.py         # Narrative brief
├── utiles/                   # UI, theme, config, secrets
├── config/                   # YAMLs editables
│   ├── feeds_rss.yaml        # 10 feeds RSS activos
│   ├── cuentas_bluesky.yaml  # OSINT handles
│   ├── chokepoints.yaml      # IDs PortWatch + display
│   ├── commodities.yaml      # Tickers yfinance agrupados
│   ├── keywords.yaml         # Filtros temáticos
│   ├── reservas.yaml         # SPR snapshot + series curadas
│   └── gas.yaml              # Gas storage snapshot + series
├── datos_cache/              # CSVs cacheados (gitignored salvo .gitkeep)
└── .streamlit/
    ├── config.toml           # Tema dark war-room
    └── secrets.toml.template # Plantilla de keys
```

## Mantenimiento

Tres tipos de datos que requieren refresh manual ocasional:

1. **`config/reservas.yaml`** — series SPR no-USA. Editar cuando salgan nuevos análisis EIA *Today In Energy* o releases coordinados IEA (1-2 veces al año).
2. **`config/gas.yaml`** — series gas storage no-USA. Editar mensualmente desde AGSI+ dashboard (EU), METI press releases (Japón), NDRC (China).
3. **`config/feeds_rss.yaml`** — algunos feeds (Reuters, AP) cambian URLs anualmente. Verificar en panel de salud del dashboard.

Lo demás se actualiza solo:
- USA SPR / gas: cache a disco 6h + EIA API
- JODI Oil: re-descarga cada 7 días
- Precios: yfinance 60s-300s TTL
- Chokepoints: PortWatch ~5-7d lag inherente
- News: RSS 10min cache, GDELT y Bluesky cerca de tiempo real

## Fuentes de datos

| Sección | Fuente | Costo |
|---------|--------|-------|
| Precios commodities | Yahoo Finance vía `yfinance` | Free, 15-20min delay |
| Chokepoint tanker counts | IMF PortWatch ArcGIS REST | Free, ~5-7d lag |
| SPR USA semanal | EIA API v2 (WCSSTUS1) | Free, rate-limited con DEMO_KEY |
| Gas USA semanal | EIA API v2 (NW2_EPG0_SWO_R48_BCF) | Free |
| Oil stocks internacional | JODI Oil World Database (CSVs) | Free, ~2m lag |
| News | RSS + GDELT DOC 2.0 | Free |
| Sentiment | Bluesky public AppView + Claude Haiku 4.5 | Bluesky free, Claude ~$0.30/mes |

## License

MIT — ver [LICENSE](LICENSE).
