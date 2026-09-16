from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    ForeignKey, Enum, UniqueConstraint, Text
)
from sqlalchemy.orm import relationship
import enum

from .database import Base


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class DividendType(str, enum.Enum):
    DIVIDEND = "DIVIDEND"
    COUPON = "COUPON"            # cedola bond / titolo di Stato (12,5% se white-list)
    CERT_COUPON = "CERT_COUPON"  # cedola certificato (26%; se condizionata è reddito diverso)


class DividendSource(str, enum.Enum):
    """Come è entrato l'evento nel sistema. Serve alla regola di riconciliazione
    'broker se presente, altrimenti Yahoo': il sync Yahoo salta un dividendo se
    per lo stesso strumento esiste già un incasso di fonte non-Yahoo nella
    finestra ex-date → pagamento."""
    IMPORT = "IMPORT"    # importato da file broker (Fineco/Directa/Trade Republic)
    YAHOO = "YAHOO"      # generato dal sync automatico da Yahoo Finance
    MANUAL = "MANUAL"    # inserito a mano
    COUPON = "COUPON"    # creato dalla conferma del piano cedole di un certificato


class PriceSource(str, enum.Enum):
    YAHOO = "YAHOO"              # chart API Yahoo Finance (default, comportamento storico)
    MANUAL = "MANUAL"            # prezzo inserito a mano dall'utente
    CUSTOM_JSON = "CUSTOM_JSON"  # fetch da endpoint JSON configurato sullo strumento


class CouponType(str, enum.Enum):
    GUARANTEED = "GUARANTEED"    # garantita
    CONDITIONAL = "CONDITIONAL"  # condizionata (barriera)


class CouponStatus(str, enum.Enum):
    PLANNED = "PLANNED"   # prevista — mai conteggiata nelle performance
    PAID = "PAID"         # confermata: ha generato un DividendEvent
    SKIPPED = "SKIPPED"   # saltata (barriera violata): nessun evento generato


class AssetClass(str, enum.Enum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    ETF = "ETF"
    CRYPTO = "CRYPTO"
    CASH = "CASH"
    COMMODITY = "COMMODITY"
    REAL_ESTATE = "REAL_ESTATE"
    OTHER = "OTHER"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    reset_requests = relationship("PasswordResetRequest", back_populates="user", cascade="all, delete-orphan")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    broker = Column(String(64), nullable=True)
    currency = Column(String(8), default="EUR")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="portfolios")
    transactions = relationship("Transaction", back_populates="portfolio", cascade="all, delete-orphan")
    dividend_events = relationship("DividendEvent", back_populates="portfolio", cascade="all, delete-orphan")


class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(32), nullable=False, index=True)
    isin = Column(String(16), unique=True, nullable=True, index=True)
    name = Column(String(256), nullable=False)
    asset_class = Column(Enum(AssetClass), default=AssetClass.EQUITY)
    currency = Column(String(8), default="USD")
    sector = Column(String(128), nullable=True)
    country = Column(String(64), nullable=True)

    # Fonte prezzo (YAHOO = comportamento storico). Per CUSTOM_JSON i campi
    # custom_* configurano l'endpoint; {ISIN} e {TICKER} nella URL sono
    # sostituiti a runtime. price_fetch_error tiene l'ultimo errore di fetch
    # (None = ultimo fetch ok) senza toccare i prezzi già salvati.
    price_source = Column(Enum(PriceSource), default=PriceSource.YAHOO, nullable=False)
    custom_url = Column(Text, nullable=True)
    custom_jsonpath_price = Column(String(256), nullable=True)
    custom_jsonpath_date = Column(String(256), nullable=True)
    price_fetch_error = Column(Text, nullable=True)
    price_fetch_error_at = Column(DateTime, nullable=True)

    price_history = relationship("PriceHistory", back_populates="instrument", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="instrument")
    dividend_events = relationship("DividendEvent", back_populates="instrument")
    coupon_schedule = relationship(
        "CouponSchedule", back_populates="instrument",
        cascade="all, delete-orphan", order_by="CouponSchedule.payment_date",
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    type = Column(Enum(TransactionType), nullable=False)
    date = Column(Date, nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)           # in transaction currency
    fees = Column(Float, default=0.0)
    currency = Column(String(8), default="EUR")
    fx_rate = Column(Float, default=1.0)            # units of original currency per 1 EUR (e.g. USD≈1.08); price / fx_rate = EUR
    notes = Column(Text, nullable=True)

    portfolio = relationship("Portfolio", back_populates="transactions")
    instrument = relationship("Instrument", back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", "date", "quantity", "price", name="uq_transaction"),
    )


class DividendEvent(Base):
    __tablename__ = "dividend_events"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    amount = Column(Float, nullable=False)          # NETTO incassato, in original currency (= gross - foreign_tax - tax)
    gross_amount = Column(Float, nullable=True)     # LORDO, in original currency
    foreign_tax_amount = Column(Float, default=0.0) # ritenuta alla fonte estera, original currency
    tax_amount = Column(Float, default=0.0)         # imposta sostitutiva italiana (26%/12,5%), original currency
    accrued_interest = Column(Float, default=0.0)   # rateo cedolare pagato all'acquisto (solo cedole bond), original currency
    currency = Column(String(8), default="EUR")
    fx_rate = Column(Float, default=1.0)
    type = Column(Enum(DividendType), default=DividendType.DIVIDEND)
    # Origine dell'evento (import broker / sync Yahoo / manuale / cedola).
    source = Column(Enum(DividendSource), default=DividendSource.IMPORT, nullable=False)
    # Compensazione minusvalenze (solo cedole certificati): l'imposta è assorbita
    # dallo zainetto fiscale, quindi netto = lordo e tasse a zero.
    minus_compensation = Column(Boolean, default=False, nullable=False)

    portfolio = relationship("Portfolio", back_populates="dividend_events")
    instrument = relationship("Instrument", back_populates="dividend_events")

    # One dividend/coupon per instrument per date per portfolio — prevents
    # re-importing the same CSV from doubling the cashed amounts.
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", "date", "type", name="uq_dividend_event"),
    )


class CouponSchedule(Base):
    """Piano cedolare di un certificato/bond strutturato. Come PriceHistory è un
    dato dello STRUMENTO (condiviso), non del portafoglio: alla conferma di una
    cedola come pagata viene creato un DividendEvent (portafoglio-specifico, tipo
    CERT_COUPON) che segue il flusso dei dividendi esistente. Le righe PLANNED
    non entrano MAI nei calcoli di performance.

    `amount_per_unit` è l'importo cedola PER UNITÀ nella valuta dello strumento
    (es. 2.50 EUR per certificato) — coerente con i dividendi Yahoo per-share:
    il totale incassato = amount_per_unit × quantità detenuta."""
    __tablename__ = "coupon_schedules"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    observation_date = Column(Date, nullable=True)          # data osservazione barriera (opzionale)
    payment_date = Column(Date, nullable=False, index=True)
    amount_per_unit = Column(Float, nullable=False)         # per unità, valuta strumento
    coupon_type = Column(Enum(CouponType), default=CouponType.CONDITIONAL, nullable=False)
    memory_effect = Column(Boolean, default=False)          # recupera cedole saltate precedenti
    status = Column(Enum(CouponStatus), default=CouponStatus.PLANNED, nullable=False)
    # Evento creato alla conferma (per tracciabilità e per resettare lo stato se
    # l'evento viene cancellato). Nessun cascade: l'evento è un incasso reale.
    dividend_event_id = Column(Integer, ForeignKey("dividend_events.id"), nullable=True)
    notes = Column(Text, nullable=True)

    instrument = relationship("Instrument", back_populates="coupon_schedule")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    close_price = Column(Float, nullable=False)
    currency = Column(String(8), default="USD")

    instrument = relationship("Instrument", back_populates="price_history")

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_price_history"),
    )


class EtfProfile(Base):
    """Look-through asset-class split + category for an ETF (from Yahoo topHoldings)."""
    __tablename__ = "etf_profiles"

    instrument_id = Column(Integer, ForeignKey("instruments.id"), primary_key=True)
    equity_pct = Column(Float, default=0.0)      # fraction 0..1
    bond_pct = Column(Float, default=0.0)
    commodity_pct = Column(Float, default=0.0)
    cash_pct = Column(Float, default=0.0)
    other_pct = Column(Float, default=0.0)
    category = Column(String(128), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class EtfHolding(Base):
    """A single underlying holding of an ETF (top-10 from Yahoo), for look-through."""
    __tablename__ = "etf_holdings"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    symbol = Column(String(32), nullable=True)
    name = Column(String(256), nullable=False)
    weight = Column(Float, default=0.0)          # fraction of the ETF (0..1)


class EtfRegionWeight(Base):
    """Geographic (region) allocation of an ETF, for the area breakdown.
    Region es.: 'Nord America', 'Europa', 'Mercati Emergenti'. Weight = fraction."""
    __tablename__ = "etf_region_weights"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    region = Column(String(48), nullable=False)
    weight = Column(Float, default=0.0)


class SecurityProfile(Base):
    """Per-symbol metadata cache (country) used to resolve the country of an ETF's
    underlying holdings during look-through. Keyed by ticker symbol."""
    __tablename__ = "security_profiles"

    symbol = Column(String(32), primary_key=True)
    country = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class EtfSectorWeight(Base):
    """Sector breakdown of an ETF (from Yahoo sectorWeightings), for look-through."""
    __tablename__ = "etf_sector_weights"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    sector_key = Column(String(64), nullable=False)   # canonical Yahoo key, e.g. "technology"
    weight = Column(Float, default=0.0)               # fraction (0..1)


class PasswordResetRequest(Base):
    """An in-app 'forgot password' request raised at login. The admin sees pending
    requests (no email infra) and resets the password manually."""
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="reset_requests")


class LoginAttempt(Base):
    """Audit trail of every login attempt (success + failure). Powers the admin
    access log and the brute-force lockout that protects an internet-exposed
    instance from bots hammering /api/auth/login."""
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(128), nullable=True, index=True)   # username/email tried
    ip_address = Column(String(64), nullable=True, index=True)
    user_agent = Column(String(256), nullable=True)
    success = Column(Boolean, default=False)
    blocked = Column(Boolean, default=False)  # rejected by lockout before checking the password
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class FxRate(Base):
    __tablename__ = "fx_rates"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    pair = Column(String(16), nullable=False)       # e.g. "EURUSD"
    rate = Column(Float, nullable=False)            # how many quote per 1 EUR

    __table_args__ = (
        UniqueConstraint("date", "pair", name="uq_fx_rate"),
    )
