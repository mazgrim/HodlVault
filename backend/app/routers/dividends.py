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
    pids = _user_portfolio_ids(current_user.id, db)
    if payload.portfolio_id not in pids:
        raise HTTPException(status_code=403, detail="Accesso negato")
    ev = models.DividendEvent(**payload.model_dump())
    db.add(ev)
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
