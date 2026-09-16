from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write
from ..services.calculations import DividendCalculator

router = APIRouter()


def _user_portfolio_ids(user_id: int, db: Session) -> List[int]:
    return [p.id for p in db.query(models.Portfolio).filter(models.Portfolio.user_id == user_id).all()]


@router.get("/", response_model=List[schemas.DividendOut])
def list_dividends(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    pids = _user_portfolio_ids(current_user.id, db)
    q = db.query(models.DividendEvent).filter(models.DividendEvent.portfolio_id.in_(pids))
    if portfolio_id:
        if portfolio_id not in pids:
            raise HTTPException(status_code=403, detail="Accesso negato")
        q = q.filter(models.DividendEvent.portfolio_id == portfolio_id)
    return q.order_by(models.DividendEvent.date.desc()).all()


@router.post("/", response_model=schemas.DividendOut, status_code=201)
def create_dividend(
    payload: schemas.DividendCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    from ..services.tax import compute_net

    pids = _user_portfolio_ids(current_user.id, db)
    if payload.portfolio_id not in pids:
        raise HTTPException(status_code=403, detail="Accesso negato")

    inst = db.query(models.Instrument).filter(models.Instrument.id == payload.instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")

    # Lordo: esplicito, oppure derivato dal netto (retro-compatibilità).
    gross = payload.gross_amount if payload.gross_amount is not None else payload.amount
    if gross is None:
        raise HTTPException(status_code=422, detail="Indicare l'importo lordo o netto")

    if payload.tax_amount is not None or payload.foreign_tax_amount is not None:
        # Tasse fornite manualmente: rispettarle.
        foreign_tax = payload.foreign_tax_amount or 0.0
        italian_tax = payload.tax_amount or 0.0
        net = gross - foreign_tax - italian_tax
    elif payload.amount is not None and payload.gross_amount is None:
        # Solo netto fornito: nessuna stima, tasse a 0.
        net, foreign_tax, italian_tax = payload.amount, 0.0, 0.0
    else:
        bd = compute_net(
            gross, payload.type, inst.asset_class, inst.country,
            accrued_interest=payload.accrued_interest,
        )
        net, foreign_tax, italian_tax = bd.net, bd.foreign_tax, bd.italian_tax

    ev = models.DividendEvent(
        portfolio_id=payload.portfolio_id,
        instrument_id=payload.instrument_id,
        date=payload.date,
        amount=round(net, 4),
        gross_amount=round(gross, 4),
        foreign_tax_amount=round(foreign_tax, 4),
        tax_amount=round(italian_tax, 4),
        accrued_interest=payload.accrued_interest,
        currency=payload.currency,
        fx_rate=payload.fx_rate,
        type=payload.type,
        source=models.DividendSource.MANUAL,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@router.post("/sync")
async def sync_dividends(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Recupera da Yahoo lo storico dividendi degli strumenti posseduti e crea
    gli eventi mancanti (proporzionali alle quote, tassati lordo→netto)."""
    if portfolio_id is not None:
        pids = _user_portfolio_ids(current_user.id, db)
        if portfolio_id not in pids:
            raise HTTPException(status_code=403, detail="Accesso negato")
    calc = DividendCalculator(db, current_user.id)
    created = await calc.sync_from_market(portfolio_id)
    return {"created": created}


def _duplicate_dto(ev: models.DividendEvent, covered_by, db: Session) -> schemas.DividendDuplicate:
    inst = db.query(models.Instrument).filter(models.Instrument.id == ev.instrument_id).first()
    return schemas.DividendDuplicate(
        id=ev.id,
        portfolio_id=ev.portfolio_id,
        date=ev.date,
        instrument_name=(inst.name if inst and inst.name else (inst.ticker if inst else "?")),
        net_eur=round(ev.amount / (ev.fx_rate or 1.0), 4),
        covered_by_date=covered_by,
    )


@router.get("/duplicates", response_model=List[schemas.DividendDuplicate])
def list_duplicate_dividends(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Anteprima: incassi Yahoo che un import reale già copre (candidati alla
    deduplica). Sola lettura — non cancella nulla."""
    if portfolio_id is not None and portfolio_id not in _user_portfolio_ids(current_user.id, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    calc = DividendCalculator(db, current_user.id)
    return [_duplicate_dto(ev, cov, db) for ev, cov in calc.find_yahoo_duplicates(portfolio_id)]


@router.post("/deduplicate", response_model=schemas.DeduplicateResult)
def deduplicate_dividends(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Rimuove gli incassi Yahoo coperti da un import reale ("broker vince").
    Ricalcola i candidati al momento (idempotente): cancella solo righe YAHOO,
    mai gli import. Ritorna la lista di ciò che è stato rimosso."""
    if portfolio_id is not None and portfolio_id not in _user_portfolio_ids(current_user.id, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    calc = DividendCalculator(db, current_user.id)
    dupes = calc.find_yahoo_duplicates(portfolio_id)
    removed = [_duplicate_dto(ev, cov, db) for ev, cov in dupes]
    for ev, _ in dupes:
        db.delete(ev)
    db.commit()
    return schemas.DeduplicateResult(deleted=len(removed), removed=removed)


@router.patch("/{div_id}/minus-compensation", response_model=schemas.DividendOut)
def toggle_minus_compensation(
    div_id: int,
    payload: schemas.DividendMinusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Attiva/disattiva retroattivamente la compensazione minusvalenza su un
    incasso cedola certificato. ON: imposta a zero, netto = lordo. OFF: ricalcola
    la stima standard (eventuali tasse manuali inserite alla conferma vanno perse)."""
    from ..services.tax import compute_net

    pids = _user_portfolio_ids(current_user.id, db)
    ev = db.query(models.DividendEvent).filter(
        models.DividendEvent.id == div_id,
        models.DividendEvent.portfolio_id.in_(pids),
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    if ev.type != models.DividendType.CERT_COUPON:
        raise HTTPException(
            status_code=400,
            detail="La compensazione minusvalenze si applica solo alle cedole di certificati",
        )

    gross = ev.gross_amount if ev.gross_amount is not None else ev.amount
    if payload.minus_compensation:
        ev.amount = round(gross, 4)
        ev.foreign_tax_amount = 0.0
        ev.tax_amount = 0.0
    else:
        bd = compute_net(gross, ev.type, ev.instrument.asset_class, ev.instrument.country)
        ev.amount = round(bd.net, 4)
        ev.foreign_tax_amount = round(bd.foreign_tax, 4)
        ev.tax_amount = round(bd.italian_tax, 4)
    ev.minus_compensation = payload.minus_compensation
    db.commit()
    db.refresh(ev)
    return ev


@router.delete("/{div_id}", status_code=204)
def delete_dividend(
    div_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    pids = _user_portfolio_ids(current_user.id, db)
    ev = db.query(models.DividendEvent).filter(
        models.DividendEvent.id == div_id,
        models.DividendEvent.portfolio_id.in_(pids),
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    # Se l'incasso era nato dalla conferma di una cedola, la riga del piano
    # torna "prevista" (è così che si annulla una conferma errata).
    linked = db.query(models.CouponSchedule).filter(
        models.CouponSchedule.dividend_event_id == ev.id
    ).all()
    for coupon in linked:
        coupon.status = models.CouponStatus.PLANNED
        coupon.dividend_event_id = None
    db.delete(ev)
    db.commit()


@router.get("/kpis", response_model=schemas.DividendKPIs)
def dividend_kpis(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = DividendCalculator(db, current_user.id)
    return calc.kpis(portfolio_id)


@router.get("/monthly", response_model=List[schemas.MonthlyDividend])
def monthly_dividends(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = DividendCalculator(db, current_user.id)
    return calc.monthly_last_12(portfolio_id)


@router.get("/projection", response_model=List[schemas.DividendProjection])
def dividend_projection(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = DividendCalculator(db, current_user.id)
    return calc.projection_12_months(portfolio_id)
