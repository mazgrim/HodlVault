from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write

router = APIRouter()

_DUPLICATE_DETAIL = (
    "Esiste già una transazione identica (stesso portafoglio, strumento, data, "
    "quantità e prezzo). Modifica uno di questi valori per distinguerla."
)


def _check_portfolio_access(portfolio_id: int, user_id: int, db: Session):
    p = db.query(models.Portfolio).filter(
        models.Portfolio.id == portfolio_id,
        models.Portfolio.user_id == user_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portafoglio non trovato")
    return p


@router.get("/", response_model=List[schemas.TransactionOut])
def list_transactions(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    portfolio_ids = [
        p.id for p in db.query(models.Portfolio).filter(models.Portfolio.user_id == current_user.id).all()
    ]
    q = db.query(models.Transaction).filter(models.Transaction.portfolio_id.in_(portfolio_ids))
    if portfolio_id:
        if portfolio_id not in portfolio_ids:
            raise HTTPException(status_code=403, detail="Accesso negato")
        q = q.filter(models.Transaction.portfolio_id == portfolio_id)
    return q.order_by(models.Transaction.date.desc()).all()


@router.post("/", response_model=schemas.TransactionOut, status_code=201)
def create_transaction(
    payload: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    _check_portfolio_access(payload.portfolio_id, current_user.id, db)
    # Verify instrument exists
    if not db.query(models.Instrument).filter(models.Instrument.id == payload.instrument_id).first():
        raise HTTPException(status_code=404, detail="Strumento non trovato")

    tx = models.Transaction(**payload.model_dump())
    db.add(tx)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL)
    db.refresh(tx)
    return tx


@router.get("/{tx_id}", response_model=schemas.TransactionOut)
def get_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    tx = _get_tx(tx_id, current_user.id, db)
    return tx


@router.put("/{tx_id}", response_model=schemas.TransactionOut)
def update_transaction(
    tx_id: int,
    payload: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    tx = _get_tx(tx_id, current_user.id, db)
    # exclude_unset: only fields actually sent are applied, so an explicit
    # null (e.g. clearing notes) is honoured while omitted fields are untouched.
    data = payload.model_dump(exclude_unset=True)
    # Moving the transaction to another portfolio / instrument (e.g. correcting
    # the ticker) is allowed, but validate the targets first.
    if data.get("portfolio_id") is not None:
        _check_portfolio_access(data["portfolio_id"], current_user.id, db)
    if data.get("instrument_id") is not None:
        if not db.query(models.Instrument).filter(models.Instrument.id == data["instrument_id"]).first():
            raise HTTPException(status_code=404, detail="Strumento non trovato")
    for k, v in data.items():
        setattr(tx, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL)
    db.refresh(tx)
    return tx


@router.delete("/{tx_id}", status_code=204)
def delete_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    tx = _get_tx(tx_id, current_user.id, db)
    db.delete(tx)
    db.commit()


def _get_tx(tx_id: int, user_id: int, db: Session) -> models.Transaction:
    portfolio_ids = [
        p.id for p in db.query(models.Portfolio).filter(models.Portfolio.user_id == user_id).all()
    ]
    tx = db.query(models.Transaction).filter(
        models.Transaction.id == tx_id,
        models.Transaction.portfolio_id.in_(portfolio_ids),
    ).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transazione non trovata")
    return tx
