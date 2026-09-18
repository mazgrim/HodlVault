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

### Backend tests
```bash
cd backend
pip install -r requirements-dev.txt
pytest            # suite in backend/tests — SQLite in-memory, nessuna rete
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

### Import CSV/Excel (`routers/import_data.py`, `services/parsers/`)

Un parser per broker (`fineco`, `directa`, `trade_republic`, `mediolanum`). Il `FinecoParser` riconosce **due export diversi**: "Movimenti Dossier Titoli" (con ISIN → compravendite + dividendi) e "Movimenti conto"/lista movimenti (senza ISIN → **solo dividendi**, con ritenuta estera reale accoppiata e storni annullati; il titolo è identificato per **nome**, `ParsedTransaction.foreign_tax` porta la ritenuta). In `import_confirm` i dividendi senza ISIN/ticker vengono agganciati per nome **solo agli strumenti già presenti nel portafoglio** (`_match_instrument_by_name`); se non c'è match la riga è saltata (mai creato uno strumento da un nome nudo). Bolli e altre imposte del conto non sono importabili (nessun modello dedicato).

Il `MediolanumParser` legge l'export "Elenco movimenti" (CSV/XLS/XLSX) **senza ISIN**. L'header ha tre colonne omonime `Divisa`, quindi il parsing è **posizionale** (non per nome colonna): salta il preambolo dossier fino alla riga header (`Titolo`+`Movimento`+`Controvalore`). Riconosce Acquisto (estero/per contante) → BUY, Vendita → SELL, "Dividendi titoli" → dividendo (Controvalore in EUR = netto, `net=gross` come il dossier Fineco); prezzo unitario EUR = `|Controvalore| / Q.tà`, `Importo` → commissioni. I movimenti "Versamento/Prelevamento titoli" (cambio denominativo) sono emessi con `ParsedTransaction.excluded=True` + `warning`: mostrati in anteprima ma **esclusi dall'import** (il frontend li filtra, `import_confirm` li salta comunque). Senza ISIN, `import_preview` suggerisce il ticker per **nome** (`_match_instrument_by_name`, esteso a compravendite oltre che ai dividendi — sicuro per gli altri broker perché le loro operazioni hanno l'ISIN) solo se il titolo è già in portafoglio; il primo acquisto di un titolo nuovo richiede il ticker manuale (l'ISIN resta facoltativo, non è recuperabile dal solo ticker via Yahoo). In anteprima **ticker e nome sono editabili** (l'identità è il ticker, quindi rinominare è sicuro; utile per nomi broker prolissi, es. suffissi "Az Fraz Mta"): la modifica si propaga alle altre righe dello stesso strumento. In `import_confirm`, per uno strumento **nuovo senza ISIN** il nome dell'anteprima è autorevole (sovrascrive il `longName` di Yahoo); con ISIN vince Yahoo come prima.

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

SQLite stored in a Docker volume (`/data/hodlvault.db`). Tables are created via `Base.metadata.create_all` on startup; **schema changes go through `app/migrations.py`** (no Alembic): version tracked with `PRAGMA user_version`, one function per step in `MIGRATIONS`, atomic transactions with automatic pre-migration file backup in `data/backups/`. Bump `TARGET_VERSION` when adding a step.

Key tables: `users`, `portfolios`, `instruments`, `transactions`, `dividend_events`, `price_history`, `coupon_schedules`, `fx_rates`.

`FxRate.pair` stores the currency code (`"USD"`, `"GBP"`…), not the full pair string. The stored `rate` (and `fx_rate` on transactions/dividends) is the **number of original-currency units per 1 EUR** — i.e. the Yahoo `EUR<CCY>=X` quote (USD ≈ 1.08, GBP ≈ 0.85). To convert to EUR you **divide**: `price_eur = price / fx_rate`. EUR rows are `1.0`. All displayed values are converted to EUR at query time using the latest stored FX rate.

### Market data

**The yfinance library is NOT a dependency.** `MarketService` (`services/market.py`) calls the Yahoo Finance chart API directly via `httpx` (`query1.finance.yahoo.com/v8/finance/chart/{ticker}`, with fallback to `query2`). This is intentional — the yfinance Python library had issues in this environment.

Prices are refreshed nightly via APScheduler (default 18:00, configurable via `PRICE_UPDATE_HOUR`). The sidebar "Aggiorna prezzi" button calls `POST /api/market/refresh` to force an immediate refresh.

### Fonti prezzo alternative (`Instrument.price_source`)

Ogni strumento ha una fonte prezzo: `YAHOO` (default), `MANUAL` (quotazioni inserite a mano via `POST /api/market/instruments/{id}/prices`; la UI avvisa se l'ultimo prezzo ha >7 giorni) o `CUSTOM_JSON` (fetch da endpoint configurato sullo strumento: `custom_url` con placeholder `{ISIN}`/`{TICKER}`, `custom_jsonpath_price`, `custom_jsonpath_date` opzionale — estrazione via `jsonpath-ng` in `services/custom_price.py`). Serve per asset non su Yahoo, es. certificati SeDeX/Cert-X.

Il refresh notturno partiziona per fonte: Yahoo come sempre, custom via endpoint (un fallimento registra l'errore in `Instrument.price_fetch_error` e mantiene l'ultimo prezzo, senza rompere il resto), manuali mai toccati. Tutti i prezzi finiscono in `price_history`, quindi grafici e calcoli funzionano identici per ogni fonte. `POST /api/market/instruments/custom-source/test` prova una config senza salvare (pulsante "Testa configurazione" in UI); `POST /api/market/instruments/{id}/refresh-price` forza il refresh di un singolo strumento custom. Enrichment, storico Yahoo e sync dividendi saltano gli strumenti non-Yahoo.

### Piano cedolare certificati (`coupon_schedules`, `routers/coupons.py`)

Il piano cedole è un dato dello **strumento** (come `price_history`), con righe `(observation_date?, payment_date, amount_per_unit, coupon_type GUARANTEED|CONDITIONAL, memory_effect, status PLANNED|PAID|SKIPPED)`. **`amount_per_unit` è l'importo per unità nella valuta dello strumento** (coerente coi dividendi Yahoo per-share): totale = per-unità × quantità. Le righe PLANNED/SKIPPED non toccano MAI i calcoli. `POST /api/coupons/{id}/confirm` (lordo effettivo, può includere cedole in memoria recuperate) crea un `DividendEvent` di tipo `CERT_COUPON` nel portafoglio scelto — da lì segue il flusso dividendi standard. Cancellare l'incasso dalla pagina Dividendi riporta la cedola a PLANNED. Alla conferma (o retroattivamente via `PATCH /api/dividends/{id}/minus-compensation`, solo `CERT_COUPON`) si può attivare il flag **compensazione minusvalenza** (`DividendEvent.minus_compensation`, migrazione v3): imposta a zero e netto = lordo; il toggle OFF ricalcola la stima standard al 26% (eventuali tasse manuali inserite alla conferma vanno perse). UI: sezione "Piano Cedole" in `InstrumentDetail` (`components/CouponScheduleSection.tsx`); la pagina Dividendi mostra inoltre il calendario "Prossime Cedole" (`GET /api/coupons/upcoming`: le PLANNED degli strumenti in posizione, con lordo stimato = per-unità × quantità detenuta — solo visualizzazione, separata dallo storico incassi e dalla proiezione). Il grafico "Dividendi/Cedole Ultimi 12 Mesi" è impilato: `GET /api/dividends/monthly` restituisce per mese `dividends` (tipo DIVIDEND) e `coupons` (COUPON + CERT_COUPON) oltre al totale `amount`.

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
| `TAX_RATE_DIVIDEND` | `0.26` | Imposta sostitutiva italiana sui dividendi azionari/ETF |
| `TAX_RATE_COUPON` | `0.125` | Imposta sostitutiva sulle cedole bond / titoli di Stato |
| `TAX_RATE_CERTIFICATE` | `0.26` | Imposta sulle cedole di certificati (`CERT_COUPON`, no ritenuta estera) |
| `FOREIGN_WHT_<ISO>` | — | Override ritenuta estera per paese (es. `FOREIGN_WHT_US=0.30`) |

### Dividendi: storico, tassazione, sync (`services/tax.py`, `DividendCalculator.sync_from_market`)

`DividendEvent` registra il **lordo** (`gross_amount`), la **ritenuta estera** (`foreign_tax_amount`), l'**imposta italiana** (`tax_amount`) e il **rateo cedolare** (`accrued_interest`); `amount` è il **netto** (= lordo − tasse), quindi il P&L realizzato (`_calc_realized_dividends`) è già al netto. `services/tax.py::compute_net` stima la doppia imposizione (ritenuta estera per paese da `Instrument.country` + 26%/12,5% italiano sul netto frontiera); se il CSV del broker fornisce la ritenuta reale (es. Trade Republic) quella ha la precedenza. `POST /api/dividends/sync` recupera da Yahoo (`chart` con `events=div`) lo storico dividendi degli strumenti posseduti (solo fonte YAHOO) e crea gli eventi proporzionali alle quote detenute alla ex-date (idempotente via UniqueConstraint). `DividendType` ha tre valori: `DIVIDEND` (26%), `COUPON` (bond, 12,5%), `CERT_COUPON` (cedole certificati, 26%, niente ritenuta estera — sottotipo tracciato per future distinzioni fiscali: le condizionate sono redditi diversi). Le colonne lordo/tasse/rateo sono state aggiunte dalla migrazione v1 in `app/migrations.py`.
