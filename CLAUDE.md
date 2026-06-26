# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview
HodlVault è un tracker di investimenti personali per uso privato.
Utenti italiani, valuta di riferimento EUR.
Supporta azioni, ETF, Bitcoin e altri asset.
Import CSV da Fineco, Directa, Trade Republic.

## Commands

### Dev environment (Docker, hot-reload)
```bash
docker compose -f docker-compose.dev.yml up --build
# Frontend: http://localhost:5173
# Backend:  http://localhost:8000
# Swagger:  http://localhost:8000/docs
```

### Production
```bash
docker compose up -d --build
# App: http://localhost:3000
```

### Without Docker

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Other useful commands
```bash
docker compose -f docker-compose.dev.yml logs -f backend   # tail backend logs
docker compose -f docker-compose.dev.yml logs -f frontend  # tail frontend logs

# Backup SQLite volume
docker run --rm -v hodlvault_hodlvault_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/hodlvault-backup-$(date +%Y%m%d).tar.gz /data
```

---

## Architecture

### Request flow

In dev, Vite proxies `/api/*` → `http://backend:8000` (`vite.config.ts`). In production, nginx (frontend container) does the same proxy. The React axios client (`src/api/client.ts`) always uses the relative base URL `/api`, so the proxy is transparent.

### Backend structure

```
backend/app/
├── main.py          # FastAPI app, CORS, router registration, APScheduler setup
├── models.py        # SQLAlchemy ORM — all tables
├── schemas.py       # Pydantic request/response models
├── auth.py          # JWT encode/decode, get_current_user, require_admin, require_write
├── database.py      # Engine + SessionLocal + Base
├── routers/         # One file per API prefix (auth, portfolio, transactions, …)
└── services/
    ├── calculations.py   # DashboardCalculator, PerformanceCalculator, DividendCalculator
    ├── market.py         # MarketService: price fetching, FX rates
    └── parsers/          # CSV importers: fineco.py, directa.py, trade_republic.py
```

**API prefixes:** `/api/auth`, `/api/portfolios`, `/api/transactions`, `/api/dividends`, `/api/performance`, `/api/market`, `/api/import`, `/api/admin`, `/api/tools`, `/api/benchmark`, `/api/demo`.

### Database

SQLite stored in a Docker volume (`/data/hodlvault.db`). Tables are created via `Base.metadata.create_all` on startup — **there are no Alembic migrations** despite `alembic` being in `requirements.txt`. Schema changes require manual migration or a DB reset.

Key tables: `users`, `portfolios`, `instruments`, `transactions`, `dividend_events`, `price_history`, `fx_rates`.

`FxRate.pair` stores the currency code (`"USD"`, `"GBP"`…), not the full pair string. The stored `rate` (and `fx_rate` on transactions/dividends) is the **number of original-currency units per 1 EUR** — i.e. the Yahoo `EUR<CCY>=X` quote (USD ≈ 1.08, GBP ≈ 0.85). To convert to EUR you **divide**: `price_eur = price / fx_rate`. EUR rows are `1.0`. All displayed values are converted to EUR at query time using the latest stored FX rate.

### Market data

**yfinance is NOT used at runtime** despite being listed in `requirements.txt`. `MarketService` (`services/market.py`) calls the Yahoo Finance chart API directly via `httpx` (`query1.finance.yahoo.com/v8/finance/chart/{ticker}`, with fallback to `query2`). This is intentional — the yfinance Python library had issues in this environment.

Prices are refreshed nightly via APScheduler (default 18:00, configurable via `PRICE_UPDATE_HOUR`). The sidebar "Aggiorna prezzi" button calls `POST /api/market/refresh` to force an immediate refresh.

### Auth

JWT access + refresh tokens, stored in `localStorage`. The axios client (`src/api/client.ts`) intercepts 401 responses, attempts a token refresh, then retries the original request. On refresh failure it clears storage and redirects to `/login`.

`require_write` dependency in `auth.py` rejects all write operations when `current_user.username == "demo"`. The demo login (`POST /api/demo/login`) creates/reuses the demo user and seeds it with static portfolio data — no password required.

### Frontend structure

```
frontend/src/
├── App.tsx              # BrowserRouter, RequireAuth wrapper, route definitions
├── api/
│   ├── client.ts        # Axios instance with auth interceptors
│   └── index.ts         # Typed API call functions grouped by domain
├── hooks/
│   └── useAuth.ts       # AuthContext provider — user state, login/logout/demo
├── context/
│   └── PortfoliosContext.tsx # Portfolio list fetching/state (replaces the old usePortfolios hook)
├── pages/               # One component per route
├── components/          # Shared UI (KpiCard, Layout, TransactionModal, …)
└── utils/format.ts      # Italian locale formatting (currency, %, dates)
```

### Calculations

`DashboardCalculator` (in `services/calculations.py`) replays all transactions in chronological order to compute open positions, unrealized P&L, realized P&L, and the portfolio value time series. `PerformanceCalculator` delegates the value series to `DashboardCalculator` then computes Sharpe, volatility (√252 annualisation), drawdown, and monthly returns. All calculations are done on-the-fly in Python — no pre-computed aggregates.

TWR (Time-Weighted Return) chains sub-period returns measured *before* each cash flow, eliminating contribution/withdrawal distortion.

### Tools page (`pages/Tools.tsx`)

Standalone financial calculators backed by `/api/tools`, organised in tabs: **Interesse Composto**, **FIRE Calculator**, **PAC vs Lump Sum**, **Inflazione**. The FIRE Calculator (`FireTool`) computes the FIRE Number (net/gross of Italian capital-gains tax), Coast FIRE, and years-to-FIRE via the exact logarithmic formula, plus a withdrawal-phase projection chart. Calculations run client-side; no data is sent to external servers.

---

## Key env vars (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | — | Required, ≥32 chars |
| `REGISTRATION_OPEN` | `true` | `false` = invite-only |
| `DEFAULT_CURRENCY` | `EUR` | Display currency |
| `PRICE_UPDATE_HOUR` | `18` | Scheduler hour (0–23) |
| `RISK_FREE_RATE` | `0.03` | Sharpe ratio risk-free rate |
| `PORT` | `3000` | Frontend container exposed port (prod only) |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins (per IP or account) before lockout |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Lockout window/duration for the login throttle |
| `LOGIN_ATTEMPT_RETENTION_DAYS` | `90` | Days the login access log is kept before pruning |
