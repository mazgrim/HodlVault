from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write

router = APIRouter()


@router.get("/", response_model=List[schemas.PortfolioOut])
def list_portfolios(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.Portfolio).filter(models.Portfolio.user_id == current_user.id).all()


@router.post("/", response_model=schemas.PortfolioOut, status_code=201)
def create_portfolio(
    payload: schemas.PortfolioCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    portfolio = models.Portfolio(**payload.model_dump(), user_id=current_user.id)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=schemas.PortfolioOut)
def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    p = _get_portfolio(portfolio_id, current_user.id, db)
    return p


@router.put("/{portfolio_id}", response_model=schemas.PortfolioOut)
def update_portfolio(
    portfolio_id: int,
    payload: schemas.PortfolioUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    p = _get_portfolio(portfolio_id, current_user.id, db)
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    p = _get_portfolio(portfolio_id, current_user.id, db)
    db.delete(p)
    db.commit()


def _get_portfolio(portfolio_id: int, user_id: int, db: Session) -> models.Portfolio:
    p = db.query(models.Portfolio).filter(
        models.Portfolio.id == portfolio_id,
        models.Portfolio.user_id == user_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portafoglio non trovato")
    return p
