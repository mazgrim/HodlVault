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
    COUPON = "COUPON"


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

    price_history = relationship("PriceHistory", back_populates="instrument", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="instrument")
    dividend_events = relationship("DividendEvent", back_populates="instrument")


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
    amount = Column(Float, nullable=False)          # in original currency
    currency = Column(String(8), default="EUR")
    fx_rate = Column(Float, default=1.0)
    type = Column(Enum(DividendType), default=DividendType.DIVIDEND)

    portfolio = relationship("Portfolio", back_populates="dividend_events")
    instrument = relationship("Instrument", back_populates="dividend_events")

    # One dividend/coupon per instrument per date per portfolio — prevents
    # re-importing the same CSV from doubling the cashed amounts.
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", "date", "type", name="uq_dividend_event"),
    )


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


class FxRate(Base):
    __tablename__ = "fx_rates"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    pair = Column(String(16), nullable=False)       # e.g. "EURUSD"
    rate = Column(Float, nullable=False)            # how many quote per 1 EUR

    __table_args__ = (
        UniqueConstraint("date", "pair", name="uq_fx_rate"),
    )
