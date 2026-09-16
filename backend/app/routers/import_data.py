import io
import logging
from typing import List
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from .. import models, schemas
from ..auth import get_current_user, require_write
from ..services.parsers.fineco import FinecoParser
from ..services.parsers.directa import DirectaParser
from ..services.parsers.trade_republic import TradeRepublicParser
from ..services.market import MarketService

logger = logging.getLogger(__name__)

router = APIRouter()

PARSERS = {
    "fineco": FinecoParser,
    "directa": DirectaParser,
    "trade_republic": TradeRepublicParser,
}


def _norm_name(s: str) -> str:
    return " ".join((s or "").upper().split())


def _match_instrument_by_name(portfolio_id: int, name: str, db: Session):
    """Resolve a security by NAME, restricted to instruments already held in this
    portfolio (they have at least one transaction here). Used for dividends imported
    from the Fineco "Movimenti conto" export, which carries no ISIN/ticker.

    Returns the instrument only on an unambiguous match; None otherwise (caller skips
    the row) — we never invent a new instrument from a bare name.
    """
    target = _norm_name(name)
    if not target:
        return None
    held = (
        db.query(models.Instrument)
        .join(models.Transaction, models.Transaction.instrument_id == models.Instrument.id)
        .filter(models.Transaction.portfolio_id == portfolio_id)
        .distinct()
        .all()
    )
    exact = [i for i in held if _norm_name(i.name) == target]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None  # ambiguo
    # Prefisso: "NVIDIA" ↔ "NVIDIA CORPORATION"
    prefix = [
        i for i in held
        if _norm_name(i.name).startswith(target + " ") or target.startswith(_norm_name(i.name) + " ")
    ]
    return prefix[0] if len(prefix) == 1 else None


def _check_portfolio(portfolio_id: int, user_id: int, db: Session):
    p = db.query(models.Portfolio).filter(
        models.Portfolio.id == portfolio_id,
        models.Portfolio.user_id == user_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portafoglio non trovato")
    return p


@router.post("/preview", response_model=schemas.ImportPreview)
async def import_preview(
    file: UploadFile = File(...),
    broker: str = Form(...),
    portfolio_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    _check_portfolio(portfolio_id, current_user.id, db)

    broker_key = broker.lower().replace(" ", "_")
    if broker_key not in PARSERS:
        raise HTTPException(status_code=400, detail=f"Broker non supportato: {broker}")

    content = await file.read()
    try:
        parser = PARSERS[broker_key]()
        rows = parser.parse(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Errore nel parsing del file: {str(e)}")

    # For rows with ISIN but no ticker, try to resolve via Yahoo Finance / DB
    svc = MarketService(db)
    unique_isins = {r.isin for r in rows if r.isin and not r.ticker}
    isin_ticker_map: dict = {}
    for isin in unique_isins:
        # Check DB first (fast)
        inst = db.query(models.Instrument).filter(models.Instrument.isin == isin).first()
        if inst:
            isin_ticker_map[isin] = inst.ticker
        else:
            # Try Yahoo Finance lookup
            try:
                info = await svc.lookup_instrument(isin=isin)
                if info and info.get("ticker"):
                    isin_ticker_map[isin] = info["ticker"]
            except Exception:
                pass

    for row in rows:
        if row.isin and not row.ticker and row.isin in isin_ticker_map:
            row.ticker = isin_ticker_map[row.isin]

    # Dividendi senza ISIN (Fineco "Movimenti conto"): suggerisci il ticker già in
    # anteprima agganciando il nome a uno strumento già presente nel portafoglio,
    # invece di lasciarlo vuoto (il match per nome girava solo in fase di conferma).
    # Resta modificabile dall'utente; se non c'è match il campo resta vuoto.
    for row in rows:
        if row.is_dividend and not row.ticker and not row.isin and row.name:
            inst = _match_instrument_by_name(portfolio_id, row.name, db)
            if inst:
                row.ticker = inst.ticker

    # Mark duplicates — transactions and dividends use different keys.
    for row in rows:
        if row.is_dividend:
            row.duplicate = _is_dividend_duplicate(portfolio_id, row, db)
        else:
            row.duplicate = _is_duplicate(portfolio_id, row, db)

    return schemas.ImportPreview(
        rows=rows,
        total=len(rows),
        duplicates=sum(1 for r in rows if r.duplicate),
    )


@router.post("/confirm", status_code=201)
async def import_confirm(
    payload: schemas.ImportConfirm,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    _check_portfolio(payload.portfolio_id, current_user.id, db)
    svc = MarketService(db)
    imported   = 0
    skipped    = 0   # duplicates
    no_ticker  = 0   # rows without a resolvable instrument

    # Track instruments that are new (just created, no price history yet)
    new_instrument_ids: set = set()
    # Track instruments that already existed (may still need history)
    seen_instrument_ids: set = set()

    for row in payload.rows:
        if row.duplicate:
            skipped += 1
            continue

        # Dividends without ISIN/ticker (Fineco "Movimenti conto"): match by name
        # against instruments already held in this portfolio. If unresolved, skip —
        # never invent an instrument from a bare name.
        if row.is_dividend and not row.ticker and not row.isin:
            instrument = _match_instrument_by_name(payload.portfolio_id, row.name, db)
            if not instrument:
                no_ticker += 1
                continue
            is_new = False
        else:
            # A row with no ticker AND no ISIN cannot be resolved at all
            if not row.ticker and not row.isin:
                no_ticker += 1
                continue

            # Check if instrument existed before this import
            existing = None
            if row.isin:
                existing = db.query(models.Instrument).filter(models.Instrument.isin == row.isin).first()
            if not existing and row.ticker:
                existing = db.query(models.Instrument).filter(models.Instrument.ticker == row.ticker).first()
            is_new = existing is None

            instrument = await svc.get_or_create_instrument(
                isin=row.isin, ticker=row.ticker, name=row.name
            )
            if not instrument:
                no_ticker += 1
                continue

        fx_rate = await svc.get_fx_rate_for_date(row.currency, row.date)
        if row.is_dividend:
            # Store amounts in ORIGINAL currency + fx_rate; the calculator converts
            # to EUR (amount / fx_rate). `row.price` is the LORDO; `row.foreign_tax`
            # is the real foreign withholding (Fineco "Movimenti conto") and
            # `row.fees` any Italian substitute tax the file reports. "CSV reale":
            # use real taxes if present, otherwise net = gross (no tax invented —
            # Fineco/Directa dossier only report the net credited).
            gross = round(row.price, 4)
            foreign = round(row.foreign_tax, 4) if row.foreign_tax else 0.0
            italian = round(row.fees, 4) if row.fees else 0.0
            obj = models.DividendEvent(
                portfolio_id=payload.portfolio_id,
                instrument_id=instrument.id,
                date=row.date,
                amount=round(gross - foreign - italian, 4),
                gross_amount=gross,
                foreign_tax_amount=foreign,
                tax_amount=italian,
                accrued_interest=0.0,
                currency=row.currency,
                fx_rate=fx_rate,
                type=models.DividendType.DIVIDEND,
                source=models.DividendSource.IMPORT,
            )
        else:
            obj = models.Transaction(
                portfolio_id=payload.portfolio_id,
                instrument_id=instrument.id,
                type=row.type,
                date=row.date,
                quantity=row.quantity,
                price=row.price,
                fees=row.fees,
                currency=row.currency,
                fx_rate=fx_rate,
            )

        # Per-row savepoint: a duplicate (unique-constraint violation) skips just
        # that row instead of aborting the whole import batch.
        try:
            with db.begin_nested():
                db.add(obj)
                db.flush()
        except IntegrityError:
            skipped += 1
            continue

        if is_new:
            new_instrument_ids.add(instrument.id)
        else:
            seen_instrument_ids.add(instrument.id)
        imported += 1

    db.commit()

    # Schedule background historical price fetch for all instruments that need it.
    # New instruments always need history; existing ones only if they have <30 price rows.
    ids_needing_history = list(new_instrument_ids)
    for iid in seen_instrument_ids:
        count = db.query(func.count(models.PriceHistory.id)).filter(
            models.PriceHistory.instrument_id == iid
        ).scalar() or 0
        if count < 30:
            ids_needing_history.append(iid)

    if ids_needing_history:
        logger.info(f"Scheduling background price history fetch for {len(ids_needing_history)} instruments")
        background_tasks.add_task(_fetch_history_for_instruments, ids_needing_history)

    return {"imported": imported, "skipped": skipped, "no_ticker": no_ticker}


async def _fetch_history_for_instruments(instrument_ids: list):
    """Background task: fetch 5-year price history for newly imported instruments."""
    if not instrument_ids:
        return
    db = SessionLocal()
    try:
        svc = MarketService(db)
        for iid in instrument_ids:
            try:
                await svc.fetch_historical_prices(iid, period="5Y")
                logger.info(f"Background: historical prices fetched for instrument {iid}")
            except Exception as exc:
                logger.warning(f"Background: price fetch failed for instrument {iid}: {exc}")
    finally:
        db.close()


def _is_duplicate(portfolio_id: int, row: schemas.ParsedTransaction, db: Session) -> bool:
    q = db.query(models.Transaction).filter(
        models.Transaction.portfolio_id == portfolio_id,
        models.Transaction.date == row.date,
        models.Transaction.quantity == row.quantity,
        models.Transaction.price == row.price,
    )
    if row.isin:
        inst = db.query(models.Instrument).filter(models.Instrument.isin == row.isin).first()
        if inst:
            q = q.filter(models.Transaction.instrument_id == inst.id)
    return q.first() is not None


def _is_dividend_duplicate(portfolio_id: int, row: schemas.ParsedTransaction, db: Session) -> bool:
    """A dividend is a duplicate if one already exists for the same portfolio,
    instrument and date (matches the uq_dividend_event constraint)."""
    inst = None
    if row.isin:
        inst = db.query(models.Instrument).filter(models.Instrument.isin == row.isin).first()
    if not inst and row.ticker:
        inst = db.query(models.Instrument).filter(models.Instrument.ticker == row.ticker).first()
    if not inst and not row.isin and not row.ticker:
        # Fineco "Movimenti conto": nessun ISIN/ticker → match per nome nel portafoglio
        inst = _match_instrument_by_name(portfolio_id, row.name, db)
    if not inst:
        return False
    return db.query(models.DividendEvent).filter(
        models.DividendEvent.portfolio_id == portfolio_id,
        models.DividendEvent.instrument_id == inst.id,
        models.DividendEvent.date == row.date,
    ).first() is not None
