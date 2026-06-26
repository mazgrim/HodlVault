# HodlVault — Portfolio Tracker self-hosted

Tracker di investimenti personale, self-hosted, in EUR. Tieni traccia di azioni,
ETF, obbligazioni e crypto in un'unica dashboard, con prezzi aggiornati
automaticamente da Yahoo Finance. Multi-utente, dark mode, import da broker.

> Uso privato. Pensato per poche persone (~10 utenti), non per servizio pubblico.

---

## Stack

| Layer | Tecnologia |
|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | React 18 + Vite + TailwindCSS + Recharts |
| Auth | JWT (access + refresh token) |
| Dati di mercato | API Yahoo Finance (chiamate dirette via `httpx`) |
| Deploy | Docker + Docker Compose |

---

## Funzionalità

- **Dashboard** — valore totale, P&L realizzato/non realizzato, rendimento TWR, grafico nel tempo e tabella posizioni.
- **Performance** — rendimento cumulativo, heatmap dei rendimenti mensili, drawdown, Sharpe ratio, volatilità.
- **Analisi** — allocazione per asset class, settore, paese e valuta; rischio di concentrazione (HHI), con *look-through* dentro gli ETF.
- **Dividendi** — storico incassi, proiezione a 12 mesi, yield-on-cost.
- **Benchmark** — confronta il tuo portafoglio con indici di mercato (es. MSCI World).
- **Import CSV** — Fineco, Directa SIM, Trade Republic, con anteprima e dedup automatica.
- **Strumenti** — calcolatori di interesse composto, FIRE, PAC vs Lump Sum, inflazione (tutto lato client).
- **Multi-utente & Admin** — gestione utenti, reset password, registro accessi e blocco automatico dopo troppi tentativi falliti (protezione anti brute-force).
- **Modalità demo** — login senza password con dati di esempio, in sola lettura.

---

## Avvio rapido (Docker)

Serve solo [Docker Desktop](https://www.docker.com/products/docker-desktop/) (o Docker Engine).

```bash
git clone <repo-url> && cd HodlVault

# 1. Crea il file di configurazione
cp .env.example .env      # su Windows: copy .env.example .env

# 2. Apri .env e imposta una SECRET_KEY lunga e casuale (almeno 32 caratteri)
#    Per generarla: openssl rand -hex 32

# 3. Avvia
docker compose -f docker-compose.dev.yml up
```

Pronto:

| Cosa | URL |
|---|---|
| App (frontend) | http://localhost:5173 |
| API (backend) | http://localhost:8000 |
| Documentazione API (Swagger) | http://localhost:8000/docs |

Il **primo account che registri diventa automaticamente admin**.

In modalità sviluppo frontend e backend hanno l'hot-reload: salvi un file e l'app si aggiorna da sola.

---

## Sviluppo senza Docker

Più veloce se hai già Python e Node installati. Servono **due terminali**.

**Backend** (Python 3.12+):
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Node 20+):
```bash
cd frontend
npm install
npm run dev
```

---

## Deploy in produzione

```bash
git clone <repo-url> /opt/hodlvault && cd /opt/hodlvault

cp .env.example .env
nano .env
#  - SECRET_KEY: stringa casuale (openssl rand -hex 32)
#  - APP_ENV=production   (l'app si rifiuta di partire con una SECRET_KEY debole)
#  - CORS_ORIGINS: l'URL pubblico dell'app

docker compose up -d --build
```

L'app è su `http://<ip-server>:3000` (cambia la porta con `PORT` nel `.env`).

**Aggiornare** all'ultima versione:
```bash
cd /opt/hodlvault && git pull && docker compose up -d --build
```

**Backup del database** (SQLite nel volume `hodlvault_hodlvault_data`):
```bash
docker run --rm -v hodlvault_hodlvault_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/hodlvault-backup-$(date +%Y%m%d).tar.gz /data
```

<details>
<summary><b>Reverse proxy con Nginx + HTTPS (opzionale)</b></summary>

```nginx
server {
    listen 80;
    server_name hodlvault.tuodominio.it;
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Poi abilita HTTPS con certbot:
```bash
sudo certbot --nginx -d hodlvault.tuodominio.it
```

> `X-Forwarded-For` è necessario perché il registro accessi e il blocco
> anti brute-force vedano l'IP reale dei client, non quello del proxy.
</details>

---

## Configurazione (`.env`)

| Variabile | Default | Descrizione |
|---|---|---|
| `SECRET_KEY` | — | **Obbligatoria** — chiave JWT, almeno 32 caratteri casuali |
| `APP_ENV` | `development` | `production` blocca l'avvio se la `SECRET_KEY` è debole |
| `REGISTRATION_OPEN` | `true` | `false` = nessuna registrazione (solo admin crea utenti) |
| `DEFAULT_CURRENCY` | `EUR` | Valuta di visualizzazione |
| `PRICE_UPDATE_HOUR` | `18` | Ora dell'aggiornamento automatico prezzi (0–23) |
| `RISK_FREE_RATE` | `0.03` | Tasso risk-free per lo Sharpe ratio (0.03 = 3%) |
| `CORS_ORIGINS` | `*` | Origini permesse; impostala all'URL pubblico in produzione |
| `LOGIN_MAX_ATTEMPTS` | `5` | Tentativi falliti (per IP o account) prima del blocco |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Durata del blocco / finestra di conteggio |
| `PORT` | `3000` | Porta pubblica del container frontend (solo produzione) |

Le variabili meno comuni (durata dei token, `DATABASE_URL`, retention del registro accessi) sono documentate in `.env.example`.

---

## Import CSV

| Broker | Dove esportare il CSV |
|---|---|
| **Fineco** | MyFineco → Titoli → Movimenti (separatore `;`, UTF-8 con BOM) |
| **Directa SIM** | Piattaforma Directa → Rendiconto → Movimenti titoli |
| **Trade Republic** | Impostazioni → Documenti → Estratto conto titoli (CSV) |

Carica il file dalla sezione **Importa**: vedrai un'anteprima delle operazioni e le righe già presenti verranno scartate automaticamente.

---

## Struttura del progetto

```
HodlVault/
├── backend/
│   └── app/
│       ├── main.py        # FastAPI app, CORS, scheduler prezzi
│       ├── models.py      # Tabelle SQLAlchemy
│       ├── schemas.py     # Schemi Pydantic (request/response)
│       ├── auth.py        # JWT, permessi (admin / scrittura)
│       ├── security.py    # Blocco login anti brute-force
│       ├── database.py    # Engine + sessione SQLite
│       ├── routers/       # Un file per area API (auth, portfolios, …)
│       └── services/
│           ├── calculations.py  # Dashboard, performance, dividendi
│           ├── market.py        # Prezzi e tassi di cambio (Yahoo)
│           └── parsers/         # Importatori CSV per broker
├── frontend/
│   └── src/
│       ├── pages/         # Una pagina per schermata (Dashboard, Analisi, …)
│       ├── components/    # UI riutilizzabile (KpiCard, Layout, modali)
│       ├── api/           # Client REST tipizzato
│       ├── context/       # Stato condiviso (auth, portafogli)
│       └── utils/         # Formattazione in locale italiano
├── docker-compose.yml      # Produzione
├── docker-compose.dev.yml  # Sviluppo (hot-reload)
└── .env.example
```

---

## Note tecniche

- **Prezzi**: aggiornati ogni giorno all'ora configurata (default 18:00) tramite uno scheduler interno. Il pulsante *"Aggiorna prezzi"* nella sidebar forza un refresh immediato.
- **Valuta**: tutto è convertito in EUR usando l'ultimo tasso di cambio salvato da Yahoo Finance.
- **Database**: SQLite, in un volume Docker. Le tabelle vengono create all'avvio; non ci sono migrazioni automatiche, quindi un cambio di schema può richiedere un reset del DB.
- **Sicurezza**: i token JWT (access + refresh) sono salvati nel browser; il login ha un blocco automatico dopo troppi tentativi falliti e un registro accessi consultabile dall'admin.
- **Dimensionamento**: ottimizzato per uso personale (~10 utenti, ~10.000 transazioni).
