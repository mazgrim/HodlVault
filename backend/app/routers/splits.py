"""
Split / raggruppamenti azionari (stock_splits).

Operazione societaria a livello di STRUMENTO (come lo storico prezzi): registra
un rapporto (old → new) a una data. Il `DashboardCalculator` normalizza le
transazioni con data precedente a termini post-split (quantità × ratio, prezzo ÷
ratio), così una posizione raggruppata si chiude correttamente e il P&L resta
giusto. I prezzi Yahoo (`close`) sono già rettificati per split, quindi il valore
storico resta coerente.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write

router = APIRouter()


@router.get("/", response_model=List[schemas.StockSplitOut])
def list_splits(
    instrument_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.StockSplit)
    if instrument_id:
        q = q.filter(models.StockSplit.instrument_id == instrument_id)
    return q.order_by(models.StockSplit.date).all()


@router.post("/", response_model=schemas.StockSplitOut, status_code=201)
def create_split(
    payload: schemas.StockSplitIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    inst = db.query(models.Instrument).filter(models.Instrument.id == payload.instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    row = models.StockSplit(
        instrument_id=payload.instrument_id,
        date=payload.date,
        old_shares=payload.old_shares,
        new_shares=payload.new_shares,
        note=(payload.note or None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esiste già uno split per questo strumento in questa data")
    db.refresh(row)
    return row


@router.delete("/{split_id}", status_code=204)
def delete_split(
    split_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    row = db.query(models.StockSplit).filter(models.StockSplit.id == split_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Split non trovato")
    db.delete(row)
    db.commit()
