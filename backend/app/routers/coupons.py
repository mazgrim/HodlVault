"""
Piano cedolare dei certificati (coupon_schedules).

Il piano è un dato dello STRUMENTO (come lo storico prezzi): le righe PLANNED
sono pura anagrafica e non toccano mai i calcoli. Solo la conferma ("pagata")
crea un DividendEvent di tipo CERT_COUPON nel portafoglio scelto, che da lì in
poi segue il flusso dei dividendi esistente (P&L realizzato, pagina Dividendi).
Una cedola SKIPPED non genera nulla.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_write
from ..services.market import MarketService
from ..services.tax import compute_net

router = APIRouter()


def _get_coupon(coupon_id: int, db: Session) -> models.CouponSchedule:
    row = db.query(models.CouponSchedule).filter(models.CouponSchedule.id == coupon_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cedola non trovata")
    return row


def _require_instrument(instrument_id: int, db: Session) -> models.Instrument:
    inst = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Strumento non trovato")
    return inst


@router.get("/", response_model=List[schemas.CouponOut])
def list_coupons(
    instrument_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.CouponSchedule)
    if instrument_id:
        q = q.filter(models.CouponSchedule.instrument_id == instrument_id)
    return q.order_by(models.CouponSchedule.payment_date).all()


@router.get("/upcoming", response_model=List[schemas.UpcomingCoupon])
def upcoming_coupons(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Calendario "Prossime Cedole" per la pagina Dividendi: tutte le cedole
    PLANNED degli strumenti attualmente in posizione (quantità > 0 nei
    portafogli dell'utente, opzionalmente filtrati), ordinate per data di
    pagamento, con il lordo stimato sulla quantità detenuta. Solo visualizzazione:
    non tocca i calcoli — le previste diventano incassi solo alla conferma."""
    pids = [
        p.id for p in db.query(models.Portfolio)
        .filter(models.Portfolio.user_id == current_user.id).all()
        if portfolio_id is None or p.id == portfolio_id
    ]
    if not pids:
        return []

    # Quantità detenuta per strumento (replay BUY − SELL)
    qty: dict[int, float] = {}
    txs = db.query(models.Transaction).filter(models.Transaction.portfolio_id.in_(pids)).all()
    for tx in txs:
        delta = tx.quantity if tx.type == models.TransactionType.BUY else -tx.quantity
        qty[tx.instrument_id] = qty.get(tx.instrument_id, 0.0) + delta
    held = {iid for iid, q in qty.items() if q > 0.0001}
    if not held:
        return []

    rows = (
        db.query(models.CouponSchedule)
        .filter(
            models.CouponSchedule.instrument_id.in_(held),
            models.CouponSchedule.status == models.CouponStatus.PLANNED,
        )
        .order_by(models.CouponSchedule.payment_date)
        .all()
    )
    if not rows:
        return []

    market = MarketService(db)
    fx_cache: dict[str, float] = {}
    out = []
    for c in rows:
        inst = c.instrument
        q = qty[c.instrument_id]
        total = c.amount_per_unit * q
        cur = inst.currency or "EUR"
        if cur not in fx_cache:
            fx_cache[cur] = market.get_fx_rate_today(cur) or 1.0
        out.append(schemas.UpcomingCoupon(
            id=c.id,
            instrument_id=inst.id,
            ticker=inst.ticker,
            name=inst.name,
            currency=cur,
            payment_date=c.payment_date,
            observation_date=c.observation_date,
            amount_per_unit=c.amount_per_unit,
            coupon_type=c.coupon_type,
            memory_effect=c.memory_effect,
            quantity=round(q, 6),
            estimated_total=round(total, 2),
            estimated_total_eur=round(total / fx_cache[cur], 2),
        ))
    return out


@router.post("/", response_model=schemas.CouponOut, status_code=201)
def create_coupon(
    payload: schemas.CouponCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    _require_instrument(payload.instrument_id, db)
    row = models.CouponSchedule(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/bulk", response_model=List[schemas.CouponOut], status_code=201)
def create_coupons_bulk(
    payload: List[schemas.CouponCreate],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Inserimento rapido di più righe (es. piano trimestrale generato da UI)."""
    if not payload:
        raise HTTPException(status_code=422, detail="Nessuna cedola da inserire")
    for item in payload:
        _require_instrument(item.instrument_id, db)
    rows = [models.CouponSchedule(**item.model_dump()) for item in payload]
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


@router.put("/{coupon_id}", response_model=schemas.CouponOut)
def update_coupon(
    coupon_id: int,
    payload: schemas.CouponUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    row = _get_coupon(coupon_id, db)
    if row.status == models.CouponStatus.PAID:
        raise HTTPException(status_code=400, detail="Cedola già pagata: elimina prima l'incasso collegato")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{coupon_id}", status_code=204)
def delete_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    row = _get_coupon(coupon_id, db)
    if row.status == models.CouponStatus.PAID:
        raise HTTPException(status_code=400, detail="Cedola già pagata: elimina prima l'incasso collegato")
    db.delete(row)
    db.commit()


@router.post("/{coupon_id}/confirm", response_model=schemas.DividendOut)
async def confirm_coupon(
    coupon_id: int,
    payload: schemas.CouponConfirm,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Conferma la cedola come pagata: crea il DividendEvent (tipo CERT_COUPON)
    e marca la riga PAID. L'importo lordo effettivo può includere cedole in
    memoria recuperate."""
    row = _get_coupon(coupon_id, db)
    if row.status != models.CouponStatus.PLANNED:
        raise HTTPException(status_code=400, detail="Solo una cedola prevista può essere confermata")

    pids = [p.id for p in db.query(models.Portfolio).filter(models.Portfolio.user_id == current_user.id).all()]
    if payload.portfolio_id not in pids:
        raise HTTPException(status_code=403, detail="Accesso negato")

    inst = row.instrument
    ev_date = payload.date or row.payment_date

    if payload.tax_amount is not None:
        # Tassa fornita manualmente (es. dal rendiconto del broker)
        gross = payload.gross_amount
        net, foreign_tax, italian_tax = gross - payload.tax_amount, 0.0, payload.tax_amount
    else:
        bd = compute_net(payload.gross_amount, models.DividendType.CERT_COUPON, inst.asset_class, inst.country)
        gross, net, foreign_tax, italian_tax = payload.gross_amount, bd.net, bd.foreign_tax, bd.italian_tax

    fx = await MarketService(db).get_fx_rate_for_date(inst.currency, ev_date)

    ev = models.DividendEvent(
        portfolio_id=payload.portfolio_id,
        instrument_id=inst.id,
        date=ev_date,
        amount=round(net, 4),
        gross_amount=round(gross, 4),
        foreign_tax_amount=round(foreign_tax, 4),
        tax_amount=round(italian_tax, 4),
        accrued_interest=0.0,
        currency=inst.currency,
        fx_rate=fx,
        type=models.DividendType.CERT_COUPON,
    )
    db.add(ev)
    try:
        db.flush()
    except Exception:
        # UniqueConstraint (portfolio, instrument, date, type): incasso già registrato
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Esiste già un incasso cedola per questo strumento in questa data",
        )

    row.status = models.CouponStatus.PAID
    row.dividend_event_id = ev.id
    db.commit()
    db.refresh(ev)
    return ev


@router.post("/{coupon_id}/skip", response_model=schemas.CouponOut)
def skip_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Marca la cedola come saltata (barriera violata): nessun evento generato."""
    row = _get_coupon(coupon_id, db)
    if row.status != models.CouponStatus.PLANNED:
        raise HTTPException(status_code=400, detail="Solo una cedola prevista può essere saltata")
    row.status = models.CouponStatus.SKIPPED
    db.commit()
    db.refresh(row)
    return row


@router.post("/{coupon_id}/reset", response_model=schemas.CouponOut)
def reset_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Riporta una cedola saltata a 'prevista' (correzione di un errore).
    Una cedola pagata si resetta eliminando l'incasso dalla pagina Dividendi."""
    row = _get_coupon(coupon_id, db)
    if row.status != models.CouponStatus.SKIPPED:
        raise HTTPException(status_code=400, detail="Solo una cedola saltata può essere ripristinata")
    row.status = models.CouponStatus.PLANNED
    db.commit()
    db.refresh(row)
    return row
