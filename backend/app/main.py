import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

from .database import engine, Base
from .migrations import run_migrations
from .frontend_static import mount_frontend
from .routers import auth, portfolio, transactions, performance, dividends, import_data, market_data, admin, tools, benchmark, demo, backup, coupons, splits

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Rileva se il file DB esisteva già PRIMA di create_all: serve a decidere se
    # le migrazioni devono fare il backup (un DB appena creato non ha dati da
    # proteggere). Vale solo per SQLite su file.
    db_pre_existed = False
    if engine.url.get_backend_name() == "sqlite" and engine.url.database not in (None, ":memory:"):
        db_pre_existed = Path(engine.url.database).exists()

    # Create tables, poi porta lo schema all'ultima versione (migrazioni atomiche
    # con backup preventivo del file DB — vedi migrations.py).
    Base.metadata.create_all(bind=engine)
    run_migrations(engine, db_pre_existed=db_pre_existed)
    logger.info("Database tables ready.")

    # Backfill historical FX (for EUR conversion of return series) in the background
    # so it never blocks the app from serving requests at startup.
    asyncio.create_task(_startup_fx_backfill())

    # Schedule nightly price update
    price_hour = int(os.getenv("PRICE_UPDATE_HOUR", 18))
    scheduler.add_job(
        _nightly_price_update,
        CronTrigger(hour=price_hour, minute=0),
        id="nightly_prices",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started – price update at {price_hour}:00 daily.")

    # Refresh prezzi all'avvio (in background, non blocca l'app). Utile all'app
    # desktop, che potrebbe non essere mai in esecuzione all'orario dello
    # scheduler. Disattivato di default: il launcher lo abilita in desktop mode.
    if os.getenv("REFRESH_ON_STARTUP", "").strip().lower() in ("1", "true", "yes", "on"):
        asyncio.create_task(_startup_price_refresh())

    yield

    scheduler.shutdown(wait=False)


async def _startup_fx_backfill():
    from .database import SessionLocal
    from .services.market import MarketService
    db = SessionLocal()
    try:
        await MarketService(db).backfill_historical_fx()
    except Exception as exc:
        logger.warning(f"Historical FX backfill at startup failed: {exc}")
    finally:
        db.close()


async def _nightly_price_update():
    from .database import SessionLocal
    from .services.market import MarketService
    db = SessionLocal()
    try:
        svc = MarketService(db)
        await svc.refresh_all_prices()
        logger.info("Nightly price update complete.")
    finally:
        db.close()


async def _startup_price_refresh():
    from .database import SessionLocal
    from .services.market import MarketService
    db = SessionLocal()
    try:
        await MarketService(db).refresh_all_prices()
        logger.info("Startup price refresh complete.")
    except Exception as exc:
        logger.warning(f"Startup price refresh failed: {exc}")
    finally:
        db.close()


app = FastAPI(
    title="HodlVault API",
    version="0.9.0",
    lifespan=lifespan,
)

# CORS — auth uses Bearer tokens (Authorization header), not cookies, so
# credentials aren't required. The wildcard origin + allow_credentials=True combo
# is also rejected by browsers, so credentials are disabled when origins is "*".
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
allow_credentials = origins != ["*"]
if origins == ["*"]:
    logger.warning(
        "CORS is open to all origins (CORS_ORIGINS=*). Set CORS_ORIGINS to your "
        "frontend URL before deploying to production."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router,         prefix="/api/auth",        tags=["Auth"])
app.include_router(portfolio.router,    prefix="/api/portfolios",  tags=["Portfolios"])
app.include_router(transactions.router, prefix="/api/transactions",tags=["Transactions"])
app.include_router(dividends.router,    prefix="/api/dividends",   tags=["Dividends"])
app.include_router(performance.router,  prefix="/api/performance", tags=["Performance"])
app.include_router(market_data.router,  prefix="/api/market",      tags=["Market"])
app.include_router(import_data.router,  prefix="/api/import",      tags=["Import"])
app.include_router(admin.router,        prefix="/api/admin",       tags=["Admin"])
app.include_router(tools.router,        prefix="/api/tools",       tags=["Tools"])
app.include_router(benchmark.router,    prefix="/api/benchmark",   tags=["Benchmark"])
app.include_router(demo.router,         prefix="/api/demo",        tags=["Demo"])
app.include_router(backup.router,       prefix="/api/backup",      tags=["Backup"])
app.include_router(coupons.router,      prefix="/api/coupons",     tags=["Coupons"])
app.include_router(splits.router,       prefix="/api/splits",      tags=["Splits"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "HodlVault"}


# Frontend statico (solo se presente una build: bundle desktop). Va montato per
# ultimo perché registra un catch-all SPA. In Docker/dev non fa nulla.
mount_frontend(app)
