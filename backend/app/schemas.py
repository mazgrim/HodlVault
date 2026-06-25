from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
from .models import TransactionType, DividendType, AssetClass


# ── Auth ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    model_config = {"from_attributes": True}

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenRefresh(BaseModel):
    refresh_token: str


# ── Portfolio ─────────────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    name: str
    broker: Optional[str] = None
    currency: str = "EUR"

class PortfolioOut(BaseModel):
    id: int
    name: str
    broker: Optional[str]
    currency: str
    created_at: datetime
    model_config = {"from_attributes": True}

class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    broker: Optional[str] = None
    currency: Optional[str] = None


# ── Instrument ────────────────────────────────────────────────────────────────

class InstrumentCreate(BaseModel):
    ticker: str
    isin: Optional[str] = None
    name: str
    asset_class: AssetClass = AssetClass.EQUITY
    currency: str = "USD"
    sector: Optional[str] = None
    country: Optional[str] = None

class InstrumentOut(BaseModel):
    id: int
    ticker: str
    isin: Optional[str]
    name: str
    asset_class: AssetClass
    currency: str
    sector: Optional[str]
    country: Optional[str]
    model_config = {"from_attributes": True}


# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    portfolio_id: int
    instrument_id: int
    type: TransactionType
    date: date
    quantity: float = Field(gt=0)
    price: float = Field(ge=0)
    fees: float = Field(default=0.0, ge=0)
    currency: str = "EUR"
    fx_rate: float = Field(default=1.0, gt=0)
    notes: Optional[str] = None

class TransactionOut(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    instrument: InstrumentOut
    type: TransactionType
    date: date
    quantity: float
    price: float
    fees: float
    currency: str
    fx_rate: float
    notes: Optional[str]
    model_config = {"from_attributes": True}

class TransactionUpdate(BaseModel):
    type: Optional[TransactionType] = None
    date: Optional[date] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, ge=0)
    fees: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    fx_rate: Optional[float] = Field(default=None, gt=0)
    notes: Optional[str] = None


# ── Dividend ──────────────────────────────────────────────────────────────────

class DividendCreate(BaseModel):
    portfolio_id: int
    instrument_id: int
    date: date
    amount: float = Field(gt=0)
    currency: str = "EUR"
    fx_rate: float = Field(default=1.0, gt=0)
    type: DividendType = DividendType.DIVIDEND

class DividendOut(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    instrument: InstrumentOut
    date: date
    amount: float
    currency: str
    fx_rate: float
    type: DividendType
    model_config = {"from_attributes": True}


# ── Market data ───────────────────────────────────────────────────────────────

class PriceHistoryOut(BaseModel):
    date: date
    close_price: float
    currency: str
    model_config = {"from_attributes": True}

class FxRateOut(BaseModel):
    date: date
    pair: str
    rate: float
    model_config = {"from_attributes": True}


# ── Dashboard KPIs ────────────────────────────────────────────────────────────

class PositionRow(BaseModel):
    instrument_id: int
    ticker: str
    name: str
    isin: Optional[str]
    asset_class: str
    currency: str
    quantity: float
    avg_cost: float          # EUR
    current_price: float     # EUR
    current_price_orig: float  # original currency
    market_value: float      # EUR
    unrealized_pnl: float    # EUR
    unrealized_pnl_pct: float
    weight_pct: float
    total_invested: float    # EUR

class DashboardKPIs(BaseModel):
    total_value: float
    total_invested: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl: float              # total realized = trades + dividends/coupons
    realized_trade_pnl: float = 0.0  # realized gains from closed trades only
    realized_dividends: float = 0.0  # dividends + coupons cashed (EUR)
    total_pnl: float = 0.0           # unrealized + realized
    annualized_return: Optional[float] = None  # TWR-based; None when < ~90 days of history
    portfolio_age_days: int
    as_of_date: date

class PortfolioChartPoint(BaseModel):
    date: date
    value: float

class PortfolioChartResponse(BaseModel):
    points: List[PortfolioChartPoint]


# ── Performance ───────────────────────────────────────────────────────────────

class PeriodReturn(BaseModel):
    period: str
    portfolio_return: Optional[float]
    benchmark_return: Optional[float]

class PerformanceMetrics(BaseModel):
    sharpe_ratio: Optional[float]
    volatility_annual: Optional[float]
    max_drawdown: Optional[float]
    period_returns: List[PeriodReturn]

class MonthlyReturn(BaseModel):
    year: int
    month: int
    return_pct: float

class DrawdownPoint(BaseModel):
    date: date
    drawdown: float


# ── Analysis ──────────────────────────────────────────────────────────────────

class AllocationItem(BaseModel):
    label: str
    value: float       # EUR
    weight_pct: float
    via_etf_pct: float = 0.0   # % (sul totale) di questa voce che proviene da dentro gli ETF

class ConcentrationRisk(BaseModel):
    top5_weight: float
    hhi: float
    top5_weight_lookthrough: float = 0.0
    hhi_lookthrough: float = 0.0
    top_name: Optional[str] = None
    top_name_pct: float = 0.0

class CompanyExposure(BaseModel):
    name: str
    symbol: Optional[str] = None
    value: float        # EUR, esposizione effettiva (diretta + dentro gli ETF)
    weight_pct: float         # % sul portafoglio (totale)
    direct_value: float       # quota detenuta direttamente
    via_etf_value: float      # quota detenuta tramite ETF (look-through)
    direct_pct: float         # % sul portafoglio detenuta direttamente
    via_etf_pct: float        # % sul portafoglio detenuta dentro gli ETF

class AnalysisResponse(BaseModel):
    by_asset_class: List[AllocationItem]
    by_sector: List[AllocationItem]
    by_country: List[AllocationItem]
    by_currency: List[AllocationItem]
    top_holdings: List[PositionRow]
    concentration: ConcentrationRisk
    company_exposure: List[CompanyExposure] = []
    lookthrough_coverage_pct: float = 0.0   # % del valore ETF effettivamente "guardato dentro"


# ── Dividends page ────────────────────────────────────────────────────────────

class DividendKPIs(BaseModel):
    total_ytd: float
    total_all_time: float
    avg_yield_on_cost: float

class DividendProjection(BaseModel):
    month: str
    amount: float

class MonthlyDividend(BaseModel):
    month: str
    amount: float


# ── Import ────────────────────────────────────────────────────────────────────

class ParsedTransaction(BaseModel):
    date: date
    type: TransactionType
    ticker: Optional[str]
    isin: Optional[str]
    name: Optional[str]
    quantity: float
    price: float
    fees: float
    currency: str
    duplicate: bool = False
    is_dividend: bool = False

class ImportPreview(BaseModel):
    rows: List[ParsedTransaction]
    total: int
    duplicates: int

class ImportConfirm(BaseModel):
    portfolio_id: int
    rows: List[ParsedTransaction]


# ── Benchmark ─────────────────────────────────────────────────────────────────

class BenchmarkInfo(BaseModel):
    ticker: str
    label: str

class BenchmarkPoint(BaseModel):
    date: str
    value: float

class BenchmarkSeries(BaseModel):
    key: str
    label: str
    color: str
    points: List[BenchmarkPoint]
    period_return: Optional[float]
    annualized_return: Optional[float]
    volatility: Optional[float]
    max_drawdown: Optional[float]

class BenchmarkChartResponse(BaseModel):
    series: List[BenchmarkSeries]


# ── Admin ─────────────────────────────────────────────────────────────────────

class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
