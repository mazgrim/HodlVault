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
