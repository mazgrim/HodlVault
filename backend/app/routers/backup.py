"""
Backup / ripristino dei dati **dell'utente autenticato**.

Regola di sicurezza fondamentale: ogni lettura parte da `current_user` e naviga
solo le sue relazioni (`user.portfolios → transactions / dividend_events`). Non
esiste alcuna query "globale" sulle tabelle, quindi il backup non può mai
contenere dati di un altro utente. Vedi il test `test_backup_isolation`.

Formati:
  • JSON completo  — per ripristino e trasferimento fra installazioni (portable
    Windows / AppImage Linux). Strumenti referenziati per ISIN/ticker, così gli
    ID numerici (che differiscono fra istanze) non contano.
  • XLSX / CSV     — lista leggibile di transazioni e dividendi (valori anche in
    EUR), per consultazione o modifica manuale.

L'import è **merge idempotente**: sfrutta le UniqueConstraint esistenti
(`uq_transaction`, `uq_dividend_event`) e un savepoint per-riga, come
`import_data.import_confirm`. Non cancella mai nulla di preesistente.
"""
import csv
import io
import json
import logging
import zipfile
from datetime import datetime, date

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openpyxl import Workbook

from ..database import get_db, SessionLocal
from .. import models, schemas
from ..auth import get_current_user, require_write

logger = logging.getLogger(__name__)

router = APIRouter()

# v2: fonte prezzo (price_source + config JSON custom), piano cedolare e storico
# prezzi degli strumenti non-Yahoo (che un restore non può riscaricare).
SCHEMA_VERSION = 2
APP_VERSION = "0.10.0"


# ── helpers: raccolta dati (SEMPRE scoped sull'utente) ────────────────────────

def _user_portfolios(user: models.User, db: Session):
    """Tutti e soli i portafogli dell'utente."""
    return (
        db.query(models.Portfolio)
        .filter(models.Portfolio.user_id == user.id)
        .order_by(models.Portfolio.id)
        .all()
    )


def _collect(user: models.User, db: Session):
    """
    Ritorna (instruments, portfolios) dove `portfolios` è una lista di dict con
    le liste `transactions` e `dividends` annidate. Gli strumenti sono solo
    quelli effettivamente referenziati dai dati dell'utente.
    """
    portfolios = _user_portfolios(user, db)
    pf_ids = [p.id for p in portfolios]

    txs = (
        db.query(models.Transaction)
        .filter(models.Transaction.portfolio_id.in_(pf_ids))
        .order_by(models.Transaction.date, models.Transaction.id)
        .all()
        if pf_ids else []
    )
    divs = (
        db.query(models.DividendEvent)
        .filter(models.DividendEvent.portfolio_id.in_(pf_ids))
        .order_by(models.DividendEvent.date, models.DividendEvent.id)
        .all()
        if pf_ids else []
    )

    # Strumenti referenziati (una sola query, nessun dato di altri utenti)
    inst_ids = {t.instrument_id for t in txs} | {d.instrument_id for d in divs}
    instruments = (
        db.query(models.Instrument)
        .filter(models.Instrument.id.in_(inst_ids))
        .order_by(models.Instrument.ticker)
        .all()
        if inst_ids else []
    )
    inst_by_id = {i.id: i for i in instruments}

    return portfolios, txs, divs, instruments, inst_by_id


def _inst_ref(inst: models.Instrument | None) -> dict:
    if not inst:
        return {"isin": None, "ticker": None}
    return {"isin": inst.isin, "ticker": inst.ticker}


# ── JSON export ───────────────────────────────────────────────────────────────

def _build_backup(user: models.User, db: Session) -> dict:
    portfolios, txs, divs, instruments, inst_by_id = _collect(user, db)

    tx_by_pf: dict[int, list] = {}
    for t in txs:
        tx_by_pf.setdefault(t.portfolio_id, []).append({
            "instrument_ref": _inst_ref(inst_by_id.get(t.instrument_id)),
            "type": t.type.value,
            "date": t.date.isoformat(),
            "quantity": t.quantity,
            "price": t.price,
            "fees": t.fees,
            "currency": t.currency,
            "fx_rate": t.fx_rate,
            "notes": t.notes,
        })

    div_by_pf: dict[int, list] = {}
    for d in divs:
        div_by_pf.setdefault(d.portfolio_id, []).append({
            "instrument_ref": _inst_ref(inst_by_id.get(d.instrument_id)),
            "date": d.date.isoformat(),
            "amount": d.amount,
            "gross_amount": d.gross_amount,
            "foreign_tax_amount": d.foreign_tax_amount,
            "tax_amount": d.tax_amount,
            "accrued_interest": d.accrued_interest,
            "currency": d.currency,
            "fx_rate": d.fx_rate,
            "type": d.type.value,
            "source": d.source.value if d.source else "IMPORT",
        })

    return {
        "hodlvault_backup": {
            "schema_version": SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "username": user.username,
        },
        "instruments": [{
            "ticker": i.ticker,
            "isin": i.isin,
            "name": i.name,
            "asset_class": i.asset_class.value if i.asset_class else "EQUITY",
            "currency": i.currency,
            "sector": i.sector,
            "country": i.country,
            "price_source": i.price_source.value if i.price_source else "YAHOO",
            "custom_url": i.custom_url,
            "custom_jsonpath_price": i.custom_jsonpath_price,
            "custom_jsonpath_date": i.custom_jsonpath_date,
            "coupon_schedule": [{
                "payment_date": c.payment_date.isoformat(),
                "observation_date": c.observation_date.isoformat() if c.observation_date else None,
                "amount_per_unit": c.amount_per_unit,
                "coupon_type": c.coupon_type.value,
                "memory_effect": c.memory_effect,
                "status": c.status.value,
                "notes": c.notes,
            } for c in i.coupon_schedule],
            # Solo per fonti manuali/custom: Yahoo si riscarica, questi no.
            "price_history": [
                {"date": r.date.isoformat(), "price": r.close_price}
                for r in sorted(i.price_history, key=lambda r: r.date)
            ] if i.price_source != models.PriceSource.YAHOO else [],
        } for i in instruments],
        "portfolios": [{
            "name": p.name,
            "broker": p.broker,
            "currency": p.currency,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "transactions": tx_by_pf.get(p.id, []),
            "dividends": div_by_pf.get(p.id, []),
        } for p in portfolios],
    }


def _download_name(prefix: str, ext: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d')}.{ext}"


@router.get("/export")
def export_json(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Backup JSON completo dei soli dati dell'utente corrente."""
    payload = _build_backup(current_user, db)
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_download_name("hodlvault_backup", "json")}"'},
    )


# ── XLSX / CSV export (leggibile) ─────────────────────────────────────────────

_TX_HEADERS = [
    "Data", "Portafoglio", "Tipo", "Ticker", "ISIN", "Nome",
    "Quantità", "Prezzo", "Valuta", "Commissioni", "Cambio (unità/EUR)",
    "Prezzo EUR", "Controvalore EUR", "Commissioni EUR", "Note",
]
_DIV_HEADERS = [
    "Data", "Portafoglio", "Tipo", "Ticker", "ISIN", "Nome",
    "Lordo", "Ritenuta estera", "Imposta IT", "Rateo", "Netto", "Valuta",
    "Cambio (unità/EUR)", "Netto EUR", "Lordo EUR",
]


def _eur(value: float | None, fx: float | None) -> float | None:
    if value is None:
        return None
    fx = fx or 1.0
    return round(value / fx, 4) if fx else None


def _readable_rows(user: models.User, db: Session):
    portfolios, txs, divs, _instruments, inst_by_id = _collect(user, db)
    pf_by_id = {p.id: p for p in portfolios}

    tx_rows = []
    for t in txs:
        inst = inst_by_id.get(t.instrument_id)
        pf = pf_by_id.get(t.portfolio_id)
        tx_rows.append([
            t.date.isoformat(),
            pf.name if pf else "",
            t.type.value,
            inst.ticker if inst else "",
            inst.isin if inst else "",
            inst.name if inst else "",
            t.quantity,
            t.price,
            t.currency,
            t.fees,
            t.fx_rate,
            _eur(t.price, t.fx_rate),
            _eur(t.quantity * t.price, t.fx_rate),
            _eur(t.fees, t.fx_rate),
            t.notes or "",
        ])

    div_rows = []
    for d in divs:
        inst = inst_by_id.get(d.instrument_id)
        pf = pf_by_id.get(d.portfolio_id)
        div_rows.append([
            d.date.isoformat(),
            pf.name if pf else "",
            d.type.value,
            inst.ticker if inst else "",
            inst.isin if inst else "",
            inst.name if inst else "",
            d.gross_amount,
            d.foreign_tax_amount,
            d.tax_amount,
            d.accrued_interest,
            d.amount,
            d.currency,
            d.fx_rate,
            _eur(d.amount, d.fx_rate),
            _eur(d.gross_amount, d.fx_rate),
        ])

    return tx_rows, div_rows


@router.get("/export.xlsx")
def export_xlsx(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Lista leggibile (2 fogli: Transazioni + Dividendi) in formato XLSX."""
    tx_rows, div_rows = _readable_rows(current_user, db)

    wb = Workbook()
    ws_tx = wb.active
    ws_tx.title = "Transazioni"
    ws_tx.append(_TX_HEADERS)
    for r in tx_rows:
        ws_tx.append(r)

    ws_div = wb.create_sheet("Dividendi")
    ws_div.append(_DIV_HEADERS)
    for r in div_rows:
        ws_div.append(r)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_download_name("hodlvault_export", "xlsx")}"'},
    )


@router.get("/export.csv")
def export_csv(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Lista leggibile in CSV. Poiché transazioni e dividendi sono due tabelle
    distinte, il download è uno ZIP con `transazioni.csv` + `dividendi.csv`
    (UTF-8 con BOM, così Excel li apre correttamente).
    """
    tx_rows, div_rows = _readable_rows(current_user, db)

    def _csv_bytes(headers, rows) -> bytes:
        sio = io.StringIO()
        w = csv.writer(sio, delimiter=";")
        w.writerow(headers)
        for r in rows:
            w.writerow(["" if c is None else c for c in r])
        return b"\xef\xbb\xbf" + sio.getvalue().encode("utf-8")

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("transazioni.csv", _csv_bytes(_TX_HEADERS, tx_rows))
        zf.writestr("dividendi.csv", _csv_bytes(_DIV_HEADERS, div_rows))
    zbuf.seek(0)
    return StreamingResponse(
        zbuf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_download_name("hodlvault_export_csv", "zip")}"'},
    )


# ── Import (merge idempotente) ────────────────────────────────────────────────

def _parse_backup_upload(content: bytes) -> dict:
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=422, detail="File JSON non valido")
    if not isinstance(data, dict) or "portfolios" not in data or "instruments" not in data:
        raise HTTPException(status_code=422, detail="Formato backup non riconosciuto")
    meta = data.get("hodlvault_backup", {})
    ver = meta.get("schema_version")
    if ver is not None and ver > SCHEMA_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"Backup creato con uno schema più recente (v{ver}); aggiorna HodlVault.",
        )
    return data


def _instrument_lookup(ref: dict, db: Session) -> models.Instrument | None:
    isin = (ref or {}).get("isin")
    ticker = (ref or {}).get("ticker")
    inst = None
    if isin:
        inst = db.query(models.Instrument).filter(models.Instrument.isin == isin).first()
    if not inst and ticker:
        inst = db.query(models.Instrument).filter(models.Instrument.ticker == ticker).first()
    return inst


def _get_or_create_instrument(spec: dict, db: Session) -> models.Instrument | None:
    """Trova per ISIN→ticker o crea da zero coi metadati del backup."""
    inst = _instrument_lookup(spec, db)
    if inst:
        return inst
    ticker = spec.get("ticker")
    isin = spec.get("isin")
    if not ticker and not isin:
        return None
    try:
        asset_class = models.AssetClass(spec.get("asset_class") or "EQUITY")
    except ValueError:
        asset_class = models.AssetClass.EQUITY
    try:
        price_source = models.PriceSource(spec.get("price_source") or "YAHOO")
    except ValueError:
        price_source = models.PriceSource.YAHOO
    inst = models.Instrument(
        ticker=ticker or (isin or ""),
        isin=isin,
        name=spec.get("name") or ticker or isin or "?",
        asset_class=asset_class,
        currency=spec.get("currency") or "USD",
        sector=spec.get("sector"),
        country=spec.get("country"),
        price_source=price_source,
        custom_url=spec.get("custom_url"),
        custom_jsonpath_price=spec.get("custom_jsonpath_price"),
        custom_jsonpath_date=spec.get("custom_jsonpath_date"),
    )
    db.add(inst)
    db.flush()
    return inst


def _import_instrument_extras(spec: dict, inst: models.Instrument, db: Session, result: dict):
    """Piano cedolare e storico prezzi (fonti non-Yahoo) dal backup v2.
    Merge idempotente senza UniqueConstraint dedicate: una riga è un duplicato
    se coincide su (data pagamento, importo) / (data, prezzo già presente)."""
    existing_coupons = {
        (c.payment_date, c.amount_per_unit)
        for c in db.query(models.CouponSchedule)
        .filter(models.CouponSchedule.instrument_id == inst.id).all()
    }
    for c in spec.get("coupon_schedule", []) or []:
        d = _parse_date(c.get("payment_date"))
        amount = c.get("amount_per_unit")
        if d is None or not amount or (d, amount) in existing_coupons:
            continue
        try:
            ctype = models.CouponType(c.get("coupon_type") or "CONDITIONAL")
            status = models.CouponStatus(c.get("status") or "PLANNED")
        except ValueError:
            continue
        db.add(models.CouponSchedule(
            instrument_id=inst.id,
            payment_date=d,
            observation_date=_parse_date(c.get("observation_date")),
            amount_per_unit=amount,
            coupon_type=ctype,
            memory_effect=bool(c.get("memory_effect")),
            status=status,   # il link all'evento non sopravvive al restore
            notes=c.get("notes"),
        ))
        existing_coupons.add((d, amount))
        result["coupons_imported"] += 1

    existing_prices = {
        r.date for r in db.query(models.PriceHistory)
        .filter(models.PriceHistory.instrument_id == inst.id).all()
    }
    for p in spec.get("price_history", []) or []:
        d = _parse_date(p.get("date"))
        price = p.get("price")
        if d is None or price is None or d in existing_prices:
            continue
        db.add(models.PriceHistory(
            instrument_id=inst.id, date=d,
            close_price=price, currency=inst.currency,
        ))
        existing_prices.add(d)
        result["prices_imported"] += 1


def _parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _do_import(data: dict, user: models.User, db: Session, dry_run: bool):
    """Ritorna un dict di conteggi. dry_run=True non committa nulla."""
    result = {
        "portfolios_created": 0,
        "instruments_created": 0,
        "transactions_imported": 0,
        "transactions_skipped": 0,
        "dividends_imported": 0,
        "dividends_skipped": 0,
        "coupons_imported": 0,
        "prices_imported": 0,
        "errors": [],
    }
    touched_instruments: set[int] = set()   # per il fetch prezzi post-import

    # Pre-crea gli strumenti dal blocco `instruments` (metadati completi),
    # poi importa gli extra v2 (piano cedolare + prezzi delle fonti non-Yahoo).
    for spec in data.get("instruments", []):
        existing = _instrument_lookup(spec, db)
        inst = _get_or_create_instrument(spec, db)
        if inst is not None:
            touched_instruments.add(inst.id)
            if existing is None:
                result["instruments_created"] += 1
            _import_instrument_extras(spec, inst, db, result)

    existing_pf = {p.name: p for p in _user_portfolios(user, db)}

    for pf in data.get("portfolios", []):
        name = pf.get("name")
        if not name:
            result["errors"].append("Portafoglio senza nome ignorato")
            continue
        portfolio = existing_pf.get(name)
        if portfolio is None:
            portfolio = models.Portfolio(
                user_id=user.id,
                name=name,
                broker=pf.get("broker"),
                currency=pf.get("currency") or "EUR",
            )
            db.add(portfolio)
            db.flush()
            existing_pf[name] = portfolio
            result["portfolios_created"] += 1

        for tr in pf.get("transactions", []):
            d = _parse_date(tr.get("date"))
            inst = _instrument_lookup(tr.get("instrument_ref"), db)
            if d is None or inst is None:
                result["transactions_skipped"] += 1
                continue
            touched_instruments.add(inst.id)
            try:
                ttype = models.TransactionType(tr.get("type"))
            except ValueError:
                result["transactions_skipped"] += 1
                continue
            obj = models.Transaction(
                portfolio_id=portfolio.id,
                instrument_id=inst.id,
                type=ttype,
                date=d,
                quantity=tr.get("quantity"),
                price=tr.get("price"),
                fees=tr.get("fees") or 0.0,
                currency=tr.get("currency") or "EUR",
                fx_rate=tr.get("fx_rate") or 1.0,
                notes=tr.get("notes"),
            )
            try:
                with db.begin_nested():
                    db.add(obj)
                    db.flush()
                result["transactions_imported"] += 1
            except IntegrityError:
                result["transactions_skipped"] += 1

        for dv in pf.get("dividends", []):
            d = _parse_date(dv.get("date"))
            inst = _instrument_lookup(dv.get("instrument_ref"), db)
            if d is None or inst is None:
                result["dividends_skipped"] += 1
                continue
            touched_instruments.add(inst.id)
            try:
                dtype = models.DividendType(dv.get("type") or "DIVIDEND")
            except ValueError:
                dtype = models.DividendType.DIVIDEND
            try:
                dsource = models.DividendSource(dv.get("source") or "IMPORT")
            except ValueError:
                dsource = models.DividendSource.IMPORT
            obj = models.DividendEvent(
                portfolio_id=portfolio.id,
                instrument_id=inst.id,
                date=d,
                amount=dv.get("amount"),
                gross_amount=dv.get("gross_amount"),
                foreign_tax_amount=dv.get("foreign_tax_amount") or 0.0,
                tax_amount=dv.get("tax_amount") or 0.0,
                accrued_interest=dv.get("accrued_interest") or 0.0,
                currency=dv.get("currency") or "EUR",
                fx_rate=dv.get("fx_rate") or 1.0,
                type=dtype,
                source=dsource,
            )
            try:
                with db.begin_nested():
                    db.add(obj)
                    db.flush()
                result["dividends_imported"] += 1
            except IntegrityError:
                result["dividends_skipped"] += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()
    result["instrument_ids"] = sorted(touched_instruments)
    return result


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Dry-run: mostra cosa verrebbe importato senza scrivere nulla."""
    content = await file.read()
    data = _parse_backup_upload(content)
    result = _do_import(data, current_user, db, dry_run=True)
    result.pop("instrument_ids", None)
    return result


@router.post("/import")
async def import_confirm(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    """Merge idempotente del backup nell'account dell'utente corrente."""
    content = await file.read()
    data = _parse_backup_upload(content)
    result = _do_import(data, current_user, db, dry_run=False)

    # Il backup non contiene prezzi/FX (si ri-scaricano da Yahoo). Senza questo
    # fetch, dopo l'import la dashboard mostrerebbe valori di mercato errati fino
    # al prossimo refresh. Rifà prezzi/FX in background (non blocca la risposta).
    ids = result.pop("instrument_ids", [])
    imported_any = (
        result["transactions_imported"]
        + result["dividends_imported"]
        + result["instruments_created"]
    ) > 0
    if imported_any:
        # Storico completo solo per gli strumenti che ne hanno poco (nuovi).
        need = [
            iid for iid in ids
            if (db.query(func.count(models.PriceHistory.id))
                  .filter(models.PriceHistory.instrument_id == iid).scalar() or 0) < 30
        ]
        background_tasks.add_task(_fetch_prices_after_import, need)

    return result


async def _fetch_prices_after_import(instrument_ids: list[int]):
    """Background: aggiorna FX + prezzi latest (tutti) e lo storico dei nuovi
    strumenti, così la dashboard mostra valori corretti dopo un ripristino."""
    from ..services.market import MarketService
    db = SessionLocal()
    try:
        svc = MarketService(db)
        try:
            await svc.refresh_all_prices()   # FX + prezzi correnti + enrich
        except Exception as exc:
            logger.warning(f"Backup import: refresh prezzi/FX fallito: {exc}")
        for iid in instrument_ids:
            try:
                await svc.fetch_historical_prices(iid, period="5Y")
            except Exception as exc:
                logger.warning(f"Backup import: storico fallito per strumento {iid}: {exc}")
        logger.info(f"Backup import: prezzi/FX aggiornati ({len(instrument_ids)} nuovi strumenti).")
    finally:
        db.close()
