# HodlVault — Self-hosted Portfolio Tracker

Finance portfolio tracker personale con supporto multi-utente, dark mode, e integrazione Yahoo Finance.

---

## Stack

| Layer | Tecnologia |
|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | React 18 + Vite + TailwindCSS + Recharts |
| Auth | JWT (access + refresh token) |
| Dati mercato | yfinance (Yahoo Finance, gratuito) |
| Deploy | Docker + Docker Compose |

---

## Funzionalità

- **Dashboard** — KPI (valore, P&L, TWR), grafico valore nel tempo, tabella posizioni
- **Performance** — Rendimento cumulativo, heatmap mensile, drawdown, Sharpe ratio
- **Analisi** — Allocazione per asset class/settore/paese/valuta, concentration risk (HHI)
- **Dividendi** — Storico incassi, proiezione 12 mesi, yield-on-cost
- **Import** — CSV Fineco, Directa SIM, Trade Republic con preview e dedup
- **Tools** — Interesse composto, FIRE calculator, PAC vs Lump Sum, inflazione
- **Admin** — Gestione utenti (abilitazione, promozione admin)

---

## Sviluppo locale (Windows + Docker Desktop)

### Prerequisiti
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) con WSL2 abilitato

### Setup

```bash
# Clona il repo
git clone <repo-url>
cd HodlVault

# Copia e personalizza le variabili d'ambiente
copy .env.example .env
# Modifica .env: almeno SECRET_KEY deve essere cambiato

# Avvia in modalità sviluppo (hot reload frontend e backend)
docker compose -f docker-compose.dev.yml up

# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# Swagger docs: http://localhost:8000/docs
```

### Sviluppo senza Docker (più veloce)

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
mkdir -p data
uvicorn app.main:app --reload --port 8000
```

**Frontend (nuova finestra):**
```bash
cd frontend
npm install
npm run dev
```

---

## Deploy su Linux Server

### Prerequisiti
- Linux (Ubuntu 22.04+ raccomandato)
- Docker Engine + Docker Compose v2
- Porta 3000 (o quella configurata) aperta nel firewall

### Deploy

```bash
# Trasferisci i file sul server (es. via scp o git)
git clone <repo-url> /opt/hodlvault
cd /opt/hodlvault

# Configura .env
cp .env.example .env
nano .env
# IMPORTANTE: cambia SECRET_KEY con una stringa random lunga
# Esempio generazione: openssl rand -hex 32

# Build e avvio
docker compose up -d --build

# Verifica
docker compose ps
docker compose logs -f
```

### Accesso
L'app sarà disponibile su `http://<ip-server>:3000`

**Primo avvio:** registra un account — il primo utente diventa automaticamente admin.

### Con Nginx come reverse proxy (opzionale)

```nginx
server {
    listen 80;
    server_name hodlvault.tuodominio.it;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Con HTTPS via certbot:
```bash
sudo certbot --nginx -d hodlvault.tuodominio.it
```

### Aggiornamenti

```bash
cd /opt/hodlvault
git pull
docker compose up -d --build
```

### Backup database

```bash
# Il database SQLite è nel volume Docker "hodlvault_hodlvault_data"
# Per farne backup:
docker run --rm -v hodlvault_hodlvault_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/hodlvault-backup-$(date +%Y%m%d).tar.gz /data
```

---

## Configurazione (.env)

| Variabile | Default | Descrizione |
|---|---|---|
| `SECRET_KEY` | — | **Obbligatorio** — chiave JWT, minimo 32 caratteri random |
| `REGISTRATION_OPEN` | `true` | `false` = solo l'admin può creare utenti |
| `DEFAULT_CURRENCY` | `EUR` | Valuta di visualizzazione |
| `PRICE_UPDATE_HOUR` | `18` | Ora aggiornamento automatico prezzi (0-23) |
| `RISK_FREE_RATE` | `0.03` | Tasso risk-free per Sharpe ratio (es. 0.03 = 3%) |
| `PORT` | `3000` | Porta esposta del container frontend |

---

## Import CSV

### Fineco
Esporta il CSV movimenti da **MyFineco → Titoli → Movimenti**. Il file usa separatore `;` e encoding UTF-8 con BOM.

### Directa SIM
Esporta il CSV da **Piattaforma Directa → Rendiconto → Movimenti titoli**.

### Trade Republic
Esporta il CSV da **Impostazioni → Documenti → Estratto conto titoli** (formato CSV).

---

## Struttura del progetto

```
HodlVault/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + scheduler
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── schemas.py       # Pydantic schemas
│   │   ├── auth.py          # JWT auth
│   │   ├── database.py      # DB setup
│   │   ├── routers/         # API endpoints
│   │   └── services/        # Business logic + parsers
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/           # Dashboard, Performance, etc.
│   │   ├── components/      # KpiCard, Layout, etc.
│   │   ├── api/             # REST client
│   │   ├── hooks/           # useAuth, usePortfolios
│   │   └── utils/format.ts  # Formattazione italiana
│   └── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
└── .env.example
```

---

## Note tecniche

- I prezzi vengono aggiornati automaticamente ogni giorno all'ora configurata (default 18:00)
- Tutti i valori sono convertiti in EUR usando i tassi di cambio da Yahoo Finance
- Il database SQLite è ottimizzato per max ~10 utenti e ~10.000 transazioni
- Il bottone "Aggiorna prezzi" nella sidebar forza un refresh immediato in background
