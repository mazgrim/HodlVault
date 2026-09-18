import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
import httpx

logger = logging.getLogger(__name__)

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write
from ..services.market import MarketService

router = APIRouter()


def _parse_pf_ids(portfolio_id: Optional[str]) -> Optional[List[int]]:
    """Query param `portfolio_id`: singolo id ("3") o lista comma-separated ("3,5")
    per la selezione multipla in Dashboard. Restituisce None (= tutti) se vuoto."""
    if not portfolio_id:
        return None
    ids = [int(x) for x in portfolio_id.split(",") if x.strip().isdigit()]
    return ids or None


@router.get("/instruments/search")
async def search_instruments(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Full-text search on Yahoo Finance: returns matching tickers for a
    name fragment or partial symbol (e.g. 'apple', 'VWCE', 'msci').
    Uses Yahoo Finance v1/finance/search API directly via httpx.
    """
    _YF_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
    _YF_SEARCH_URL_2 = "https://query2.finance.yahoo.com/v1/finance/search"
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    params = {
        "q": q,
        "quotesCount": limit,
        "newsCount": 0,
        "enableFuzzyQuery": "false",
        "enableNavLinks": "false",
    }

    data = None
    async with httpx.AsyncClient(timeout=8.0) as client:
        for url in (_YF_SEARCH_URL, _YF_SEARCH_URL_2):
            try:
                resp = await client.get(url, params=params, headers=_HEADERS)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                logger.warning(f"Yahoo Finance search ({url}) failed for '{q}': {exc}")

    if not data:
        return []

    quotes = data.get("quotes", [])
    out = []
    for item in quotes:
        sym = item.get("symbol", "").strip()
        if not sym:
            continue
        out.append({
            "ticker":   sym,
            "name":     item.get("longname") or item.get("shortname") or sym,
            "type":     item.get("typeDisp") or item.get("quoteType", ""),
            "exchange": item.get("exchDisp") or item.get("exchange", ""),
        })
    return out[:limit]


@router.get("/instruments", response_model=List[schemas.InstrumentOut])
def list_instruments(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.Instrument).order_by(models.Instrument.name).all()


@router.post("/instruments", response_model=schemas.InstrumentOut, status_code=201)
def create_instrument(
    payload: schemas.InstrumentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    existing = None
    if payload.isin:
        existing = db.query(models.Instrument).filter(models.Instrument.isin == payload.isin).first()
    if not existing:
        existing = db.query(models.Instrument).filter(models.Instrument.ticker == payload.ticker).first()
    if existing:
        return existing
    inst = models.Instrument(**payload.model_dump())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


@router.patch("/instruments/{instrument_id}", response_model=schemas.InstrumentOut)
def update_instrument(
    instrument_id: int,
    payload: schemas.InstrumentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Aggiorna anagrafica e fonte prezzo. Cambiare fonte/config azzera l'ultimo
    errore di fetch (la nuova config riparte pulita); i prezzi già in storico
    restano validi qualunque sia la fonte."""
    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(inst, field, value)
    if {"price_source", "custom_url", "custom_jsonpath_price", "custom_jsonpath_date"} & data.keys():
        inst.price_fetch_error = None
        inst.price_fetch_error_at = None
    db.commit()
    db.refresh(inst)
    return inst


@router.post("/instruments/custom-source/test", response_model=schemas.CustomSourceTestOut)
async def test_custom_source(
    payload: schemas.CustomSourceTestIn,
    current_user: models.User = Depends(require_write),
):
    """Chiamata di prova della fonte JSON: fetch + estrazione, nessun salvataggio."""
    from ..services.custom_price import CustomPriceError, fetch_custom_price

    try:
        price, price_date, resolved = await fetch_custom_price(
            payload.url, payload.jsonpath_price, payload.jsonpath_date,
            isin=payload.isin, ticker=payload.ticker,
        )
    except CustomPriceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return schemas.CustomSourceTestOut(price=price, price_date=price_date, resolved_url=resolved)


@router.post("/instruments/{instrument_id}/prices", response_model=schemas.PriceHistoryOut, status_code=201)
def upsert_manual_price(
    instrument_id: int,
    payload: schemas.ManualPriceIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Inserisce/aggiorna una quotazione (data + prezzo, valuta dello strumento).
    Pensato per la fonte manuale, ma utilizzabile anche per correggere un punto
    di una fonte custom."""
    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    svc = MarketService(db)
    svc._upsert_price(instrument_id, payload.date, payload.price, inst.currency)
    db.commit()
    row = db.query(models.PriceHistory).filter(
        models.PriceHistory.instrument_id == instrument_id,
        models.PriceHistory.date == payload.date,
    ).first()
    return row


@router.delete("/instruments/{instrument_id}/prices/{price_date}", status_code=204)
def delete_manual_price(
    instrument_id: int,
    price_date: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    from datetime import date as _date
    try:
        d = _date.fromisoformat(price_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Data non valida (attesa ISO YYYY-MM-DD)")
    row = db.query(models.PriceHistory).filter(
        models.PriceHistory.instrument_id == instrument_id,
        models.PriceHistory.date == d,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Quotazione non trovata")
    db.delete(row)
    db.commit()


@router.post("/instruments/{instrument_id}/refresh-price", response_model=schemas.InstrumentOut)
async def refresh_instrument_price(
    instrument_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Refresh immediato del prezzo di un singolo strumento CUSTOM_JSON
    (il pulsante "Aggiorna ora" della pagina strumento)."""
    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    if inst.price_source != models.PriceSource.CUSTOM_JSON:
        raise HTTPException(status_code=400, detail="Refresh disponibile solo per fonte JSON custom")
    svc = MarketService(db)
    await svc.refresh_custom_price(inst)
    db.commit()
    db.refresh(inst)
    return inst


@router.get("/instruments/lookup")
async def lookup_instrument(
    isin: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Lookup instrument info from Yahoo Finance by ISIN or ticker."""
    if not isin and not ticker:
        raise HTTPException(status_code=400, detail="Fornire isin o ticker")
    svc = MarketService(db)
    result = await svc.lookup_instrument(isin=isin, ticker=ticker)
    if not result:
        raise HTTPException(status_code=404, detail="Strumento non trovato su Yahoo Finance")
    return result


@router.get("/instruments/{instrument_id}/detail")
def instrument_detail(
    instrument_id: int,
    portfolio_id: Optional[str] = Query(None, description="Filtra il dettaglio su un portafoglio (id singolo o lista comma-separated); vuoto = tutti"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns instrument metadata, open-position KPIs, personal transactions and
    dividends. Lo stesso ticker è un unico strumento condiviso tra i portafogli
    (prezzi/dividendi comuni); con `portfolio_id` la vista è ristretta a quel
    portafoglio, così lo stesso titolo su broker diversi non viene mischiato
    (transazioni, dividendi e posizione riflettono solo lo scope scelto).
    """
    from ..services.calculations import DashboardCalculator, _user_portfolio_ids

    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")

    scope = _parse_pf_ids(portfolio_id)
    pids = _user_portfolio_ids(current_user.id, db, scope)

    txs = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.instrument_id == instrument_id,
            models.Transaction.portfolio_id.in_(pids),
        )
        .order_by(models.Transaction.date)
        .all()
    )

    divs = (
        db.query(models.DividendEvent)
        .filter(
            models.DividendEvent.instrument_id == instrument_id,
            models.DividendEvent.portfolio_id.in_(pids),
        )
        .order_by(models.DividendEvent.date)
        .all()
    )

    # Portafogli (dell'utente) che detengono questo strumento — popolano il filtro
    # in UI mostrando solo i broker rilevanti. Calcolati su TUTTI i portafogli,
    # indipendentemente dallo scope corrente.
    all_pids = _user_portfolio_ids(current_user.id, db)
    holding_ids = {
        r[0] for r in db.query(models.Transaction.portfolio_id)
        .filter(models.Transaction.instrument_id == instrument_id,
                models.Transaction.portfolio_id.in_(all_pids)).distinct()
    } | {
        r[0] for r in db.query(models.DividendEvent.portfolio_id)
        .filter(models.DividendEvent.instrument_id == instrument_id,
                models.DividendEvent.portfolio_id.in_(all_pids)).distinct()
    }
    holding_portfolios = (
        db.query(models.Portfolio)
        .filter(models.Portfolio.id.in_(holding_ids))
        .order_by(models.Portfolio.name)
        .all()
    )

    # Open position KPIs — ristrette allo scope selezionato.
    calc = DashboardCalculator(db, current_user.id)
    positions = calc.open_positions(scope)
    position = next((p for p in positions if p.instrument_id == instrument_id), None)

    buy_dates = [tx.date.isoformat() for tx in txs if tx.type == models.TransactionType.BUY]
    sell_dates = [tx.date.isoformat() for tx in txs if tx.type == models.TransactionType.SELL]

    svc = MarketService(db)
    last_price_date = svc.latest_price_date(instrument_id)

    return {
        "instrument": {
            "id": inst.id,
            "ticker": inst.ticker,
            "isin": inst.isin,
            "name": inst.name,
            "asset_class": inst.asset_class.value,
            "currency": inst.currency,
            "sector": inst.sector,
            "country": inst.country,
            "price_source": inst.price_source.value if inst.price_source else "YAHOO",
            "custom_url": inst.custom_url,
            "custom_jsonpath_price": inst.custom_jsonpath_price,
            "custom_jsonpath_date": inst.custom_jsonpath_date,
            "price_fetch_error": inst.price_fetch_error,
            "price_fetch_error_at": inst.price_fetch_error_at.isoformat() if inst.price_fetch_error_at else None,
            "last_price_date": last_price_date.isoformat() if last_price_date else None,
        },
        "position": {
            "quantity":            position.quantity,
            "avg_cost":            position.avg_cost,
            "current_price":       position.current_price,
            "current_price_orig":  position.current_price_orig,
            "market_value":        position.market_value,
            "unrealized_pnl":      position.unrealized_pnl,
            "unrealized_pnl_pct":  position.unrealized_pnl_pct,
            "weight_pct":          position.weight_pct,
            "total_invested":      position.total_invested,
        } if position else None,
        "transactions": [
            {
                "id":        tx.id,
                "date":      tx.date.isoformat(),
                "type":      tx.type.value,
                "quantity":  tx.quantity,
                "price":     tx.price,
                "fees":      tx.fees,
                "currency":  tx.currency,
                "fx_rate":   tx.fx_rate,
                "total_eur": round(tx.quantity * tx.price / (tx.fx_rate or 1), 2),
            }
            for tx in txs
        ],
        "dividends": [
            {
                "id":       div.id,
                "date":     div.date.isoformat(),
                "amount":   div.amount,
                "currency": div.currency,
                "type":     div.type.value,
            }
            for div in divs
        ],
        "buy_dates": buy_dates,
        "sell_dates": sell_dates,
        # Portafogli che detengono lo strumento — per il filtro in UI.
        "portfolios": [
            {"id": p.id, "name": p.name, "broker": p.broker}
            for p in holding_portfolios
        ],
    }


@router.get("/instruments/{instrument_id}/price-chart")
async def instrument_price_chart(
    instrument_id: int,
    period: str = Query("1A"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Fetch price history for the chosen period (DB first, then live Yahoo Finance)."""
    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    svc = MarketService(db)
    points = await svc.get_price_chart(instrument_id, period)
    return {"points": points}


@router.get("/instruments/{instrument_id}/prices", response_model=List[schemas.PriceHistoryOut])
def instrument_prices(
    instrument_id: int,
    period: str = Query("1Y"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    svc = MarketService(db)
    return svc.get_prices(instrument_id, period)


@router.post("/refresh", status_code=202)
async def refresh_prices(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Trigger manual price refresh (runs in background)."""
    svc = MarketService(db)
    background_tasks.add_task(svc.refresh_all_prices)
    return {"message": "Aggiornamento prezzi avviato in background"}


@router.post("/enrich", status_code=202)
async def enrich_instruments(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-fetch anche gli strumenti già arricchiti"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Arricchisce gli strumenti con settore/paese (azioni) e look-through (ETF)."""
    from ..database import SessionLocal

    async def _bg(only_missing: bool):
        _db = SessionLocal()
        try:
            await MarketService(_db).enrich_all(only_missing=only_missing)
        finally:
            _db.close()

    background_tasks.add_task(_bg, not force)
    return {"message": "Arricchimento dati avviato in background"}


@router.post("/refresh-history", status_code=202)
async def refresh_history(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """
    Fetch 5-year price history for all instruments that have fewer than 30 price rows.
    Use this once after importing instruments from a new broker.
    """
    from sqlalchemy import func
    from ..database import SessionLocal

    instruments = db.query(models.Instrument).all()
    needs_history = []
    for inst in instruments:
        count = db.query(func.count(models.PriceHistory.id)).filter(
            models.PriceHistory.instrument_id == inst.id
        ).scalar() or 0
        if count < 30:
            needs_history.append(inst.id)

    if not needs_history:
        return {"message": "Tutti gli strumenti hanno già dati storici sufficienti", "count": 0}

    async def _bg(ids: list):
        _db = SessionLocal()
        try:
            svc = MarketService(_db)
            for iid in ids:
                try:
                    await svc.fetch_historical_prices(iid, period="5Y")
                    logger.info(f"History refreshed for instrument {iid}")
                except Exception as exc:
                    logger.warning(f"History refresh failed for instrument {iid}: {exc}")
        finally:
            _db.close()

    background_tasks.add_task(_bg, needs_history)
    return {
        "message": f"Caricamento storico avviato per {len(needs_history)} strumenti in background",
        "count": len(needs_history),
    }


@router.get("/fx-rates", response_model=List[schemas.FxRateOut])
def fx_rates(
    pair: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.FxRate)
    if pair:
        q = q.filter(models.FxRate.pair == pair)
    return q.order_by(models.FxRate.date.desc()).limit(100).all()


@router.get("/dashboard/kpis", response_model=schemas.DashboardKPIs)
def dashboard_kpis(
    portfolio_id: Optional[str] = Query(None, description="Id singolo o lista comma-separated (selezione multipla)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, current_user.id)
    return calc.kpis(_parse_pf_ids(portfolio_id))


@router.get("/dashboard/positions", response_model=List[schemas.PositionRow])
def open_positions(
    portfolio_id: Optional[str] = Query(None, description="Id singolo o lista comma-separated (selezione multipla)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, current_user.id)
    return calc.open_positions(_parse_pf_ids(portfolio_id))


@router.get("/dashboard/closed-positions", response_model=List[schemas.ClosedPositionRow])
def closed_positions(
    portfolio_id: Optional[str] = Query(None, description="Id singolo o lista comma-separated (selezione multipla)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, current_user.id)
    return calc.closed_positions(_parse_pf_ids(portfolio_id))


@router.get("/dashboard/chart", response_model=schemas.PortfolioChartResponse)
def portfolio_chart(
    portfolio_id: Optional[str] = Query(None, description="Id singolo o lista comma-separated (selezione multipla)"),
    period: str = Query("1Y"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, current_user.id)
    return calc.portfolio_chart(_parse_pf_ids(portfolio_id), period)


@router.get("/analysis", response_model=schemas.AnalysisResponse)
def portfolio_analysis(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..services.calculations import DashboardCalculator
    calc = DashboardCalculator(db, current_user.id)
    return calc.analysis(portfolio_id)
