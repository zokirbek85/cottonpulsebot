# 🌿 CottonPulseBot

**Public Telegram bot for live cotton, yarn, and FX market monitoring.**

Live data · No database · No Redis · Docker-ready · VPS-compatible

---

## Features

| Category | Commands |
|---|---|
| **Cotton** | `/cotton` `/ice` `/cotlook` |
| **Yarn** | `/yarn` `/china` `/india` `/pakistan` |
| **FX** | `/usd` |
| **Analytics** | `/history` `/compare` `/forecast` |
| **Alerts** | `/alert` `/alerts` `/removealert` |
| **Reports** | `/daily` `/weekly` |
| **Exports** | `/pdf` `/excel` |
| **General** | `/start` `/help` `/status` |

---

## Data Sources

| Data | Source | Fallback |
|---|---|---|
| ICE Cotton Futures | Yahoo Finance (CT=F) via yfinance | Stale cache |
| Cotlook A Index | IndexMundi / TradingEconomics scraping | ICE + 4 c/lb premium estimate |
| China Yarn | Fiber2Fashion textile exchange | Cotton price model |
| India Yarn | Fiber2Fashion textile exchange | Cotton price model |
| Pakistan Yarn | Fiber2Fashion textile exchange | Cotton price model |
| USD/UZS | CBU Uzbekistan JSON API (cbu.uz) | open.er-api.com |

> Yarn prices derived with: `yarn_USD/kg = cotton_USD/kg × 1.15 + spinning_margin`
> where margins are: China $1.10, India $0.95, Pakistan $0.90 /kg

---

## Quick Start

### 1. Get Bot Token

1. Open Telegram → [@BotFather](https://t.me/BotFather)
2. `/newbot` → follow instructions
3. Copy your token

### 2. Configure Environment

```bash
cp .env.example .env
nano .env  # Set BOT_TOKEN=your_token_here
```

### 3. Run with Docker (Recommended)

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### 4. Run Locally (Development)

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your BOT_TOKEN

python -m bot.main
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ Yes | — | Telegram bot token from @BotFather |
| `ADMIN_IDS` | No | `""` | Comma-separated admin Telegram IDs |
| `LOG_LEVEL` | No | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |
| `CACHE_TTL` | No | `300` | Cache TTL in seconds (5 min) |
| `ALERT_CHECK_INTERVAL` | No | `60` | Seconds between alert checks |
| `USER_RATE_LIMIT` | No | `2` | Seconds between user requests |
| `MAX_ALERTS_PER_USER` | No | `10` | Max alerts per user |
| `ALERT_COOLDOWN_MINUTES` | No | `30` | Minutes between repeated alert fires |
| `HTTP_PROXY` | No | `""` | HTTP proxy for outbound requests |

---

## VPS Deployment

### Prerequisites

- Ubuntu 22.04+ or Debian 12+
- Docker + Docker Compose
- 512 MB RAM minimum

### Setup

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Clone or upload project
git clone <repo-url> /opt/cottonpulsebot
cd /opt/cottonpulsebot

# Configure
cp .env.example .env
nano .env   # Set BOT_TOKEN

# Start
docker compose up -d

# Auto-start on reboot (already handled by restart: unless-stopped)
```

### Monitoring

```bash
# View live logs
docker compose logs -f cottonpulsebot

# Check container health
docker compose ps

# Restart if needed
docker compose restart cottonpulsebot

# Update bot (after code changes)
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## Alert System

Create alerts interactively with `/alert`:

```
/alert
→ Choose: ICE Cotton | Cotlook A | Yarn (CN/IN/PK) | USD/UZS
→ Choose: Price Above | Price Below | Rise +% | Fall -%
→ Enter threshold value
→ Alert created ✅
```

**Examples:**
- Cotton above 80 c/lb
- Cotton below 70 c/lb
- China Yarn rises +3%
- USD/UZS above 13000

Alerts fire with **30-minute cooldown** to prevent spam.  
Each user can hold up to **10 active alerts**.

---

## Price Conversions

**Cotton (c/lb → other)**

```
USD/kg = c/lb × 0.022046
UZS/kg = USD/kg × USD/UZS_rate
```

**Yarn (USD/kg → other)**

```
UZS/kg = USD/kg × USD/UZS_rate
USD/lb = USD/kg × 0.453592
```

---

## Architecture

```
bot/
├── main.py              — Bot init, middleware, polling
├── config.py            — Settings from .env (pydantic-settings)
├── state.py             — In-memory state (alerts, history, cache)
├── handlers/
│   ├── general.py       — /start /help /status
│   ├── cotton.py        — /cotton /ice /cotlook
│   ├── yarn.py          — /yarn /china /india /pakistan
│   ├── fx.py            — /usd
│   ├── analytics.py     — /history /compare /forecast
│   ├── alerts.py        — /alert /alerts /removealert (FSM)
│   ├── reports.py       — /daily /weekly
│   └── exports.py       — /pdf /excel
├── services/
│   ├── cache_manager.py — Async TTL cache
│   ├── ice_cotton.py    — yfinance CT=F fetcher
│   ├── cotlook.py       — Multi-source Cotlook A
│   ├── yarn_sources.py  — Multi-source yarn prices
│   └── fx_service.py    — CBU + er-api FX rates
├── schedulers/
│   └── alert_scheduler.py — APScheduler price check loop
├── exports/
│   ├── pdf_generator.py — ReportLab PDF
│   └── excel_generator.py — openpyxl Excel
└── utils/
    ├── converters.py    — Unit math
    ├── formatters.py    — Message templates
    └── keyboards.py     — Inline/reply keyboards
```

---

## Troubleshooting

**Bot doesn't start**
```bash
docker compose logs cottonpulsebot | tail -50
# Check: BOT_TOKEN is set correctly in .env
```

**No ICE Cotton data**
```
ICE data comes from Yahoo Finance (yfinance). This is occasionally rate-limited.
The bot falls back to stale cached data and retries automatically.
```

**Cotlook A shows "estimated"**
```
Cotlook A Index is behind a subscription paywall. The bot scrapes public sources
and falls back to a derived estimate (ICE + 4 c/lb premium) when scraping fails.
This is standard industry practice.
```

**Yarn shows "est."**
```
Live yarn prices from country-specific exchanges are not publicly accessible via API.
The bot attempts web scraping then falls back to the cotton-to-yarn conversion model.
```

**USD/UZS shows stale data**
```
Primary: Central Bank of Uzbekistan API (cbu.uz). Updated daily by CBU.
Fallback: open.er-api.com (updated hourly, free tier).
```

**Out of memory on VPS**
```
Edit docker-compose.yml → reduce memory limit or add swap:
sudo fallocate -l 1G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

---

## License

MIT — free to use, modify, and deploy.

---

*CottonPulseBot — Built with aiogram 3.x · Python 3.12*
# cottonpulsebot
