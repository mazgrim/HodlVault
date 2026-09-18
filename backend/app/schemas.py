from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator, computed_field
from .models import TransactionType, DividendType, DividendSource, AssetClass, PriceSource, CouponType, CouponStatus

# Alias to the date type. Some models have a field literally named `date`; an
# annotated assignment like `date: Optional[date] = None` rebinds `date` to the
# default in the class namespace *before* the annotation is evaluated, so the
# annotation would resolve to NoneType and reject every real date. Referencing
# the type through this alias sidesteps the shadowing.
_Date = date


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

class AuthConfig(BaseModel):
    """Config pubblica letta dal frontend all'avvio (prima del login)."""
    desktop_mode: bool
    registration_open: bool
    needs_setup: bool = False   # desktop: primo avvio, nessun utente ancora creato

class DesktopSetup(BaseModel):
    username: str = Field(min_length=1, max_length=64)

class TokenRefresh(BaseModel):
    refresh_token: str

class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)

class ForgotPasswordRequest(BaseModel):
    identifier: str   # username or email

class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8)

class PasswordResetRequestOut(BaseModel):
    id: int
    user_id: int
    username: str
    email: str
    created_at: datetime


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
    price_source: PriceSource = PriceSource.YAHOO
    custom_url: Optional[str] = None
    custom_jsonpath_price: Optional[str] = None
    custom_jsonpath_date: Optional[str] = None

class InstrumentUpdate(BaseModel):
    ticker: Optional[str] = None
    isin: Optional[str] = None
    name: Optional[str] = None
    asset_class: Optional[AssetClass] = None
    currency: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    price_source: Optional[PriceSource] = None
    custom_url: Optional[str] = None
    custom_jsonpath_price: Optional[str] = None
    custom_jsonpath_date: Optional[str] = None

class InstrumentOut(BaseModel):
    id: int
    ticker: str
    isin: Optional[str]
    name: str
    asset_class: AssetClass
    currency: str
    sector: Optional[str]
    country: Optional[str]
    price_source: PriceSource = PriceSource.YAHOO
    custom_url: Optional[str] = None
    custom_jsonpath_price: Optional[str] = None
    custom_jsonpath_date: Optional[str] = None
    price_fetch_error: Optional[str] = None
    price_fetch_error_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

class ManualPriceIn(BaseModel):
    date: date
    price: float = Field(gt=0)

class CustomSourceTestIn(BaseModel):
    """Prova di configurazione fonte JSON: fetch + estrazione senza salvare."""
    url: str
    jsonpath_price: str
    jsonpath_date: Optional[str] = None
    isin: Optional[str] = None
    ticker: Optional[str] = None

class CustomSourceTestOut(BaseModel):
    price: float
    price_date: date
    resolved_url: str


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
    portfolio_id: Optional[int] = None
    instrument_id: Optional[int] = None
    type: Optional[TransactionType] = None
    date: Optional[_Date] = None
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
    # `amount` (netto) resta accettato per retro-compatibilità; se non sono
    # indicate le tasse, il router stima il netto da `gross_amount`.
    amount: Optional[float] = Field(default=None, gt=0)
    gross_amount: Optional[float] = Field(default=None, gt=0)
    foreign_tax_amount: Optional[float] = Field(default=None, ge=0)
    tax_amount: Optional[float] = Field(default=None, ge=0)
    accrued_interest: float = Field(default=0.0, ge=0)
    currency: str = "EUR"
    fx_rate: float = Field(default=1.0, gt=0)
    type: DividendType = DividendType.DIVIDEND

class DividendOut(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    instrument: InstrumentOut
    date: date
    amount: float                                 # NETTO (orig ccy)
    gross_amount: Optional[float] = None          # LORDO (orig ccy)
    foreign_tax_amount: float = 0.0
    tax_amount: float = 0.0
    accrued_interest: float = 0.0
    currency: str
    fx_rate: float
    type: DividendType
    source: DividendSource = DividendSource.IMPORT
    minus_compensation: bool = False

    @computed_field
    @property
    def foreign_tax_rate(self) -> float:
        gross = self.gross_amount or self.amount
        return round(self.foreign_tax_amount / gross, 4) if gross else 0.0

    @computed_field
    @property
    def italian_tax_rate(self) -> float:
        gross = self.gross_amount or self.amount
        base = (gross or 0.0) - self.accrued_interest - self.foreign_tax_amount
        return round(self.tax_amount / base, 4) if base > 0 else 0.0

    model_config = {"from_attributes": True}


class DividendDuplicate(BaseModel):
    """Un incasso YAHOO coperto da un import reale (candidato alla deduplica)."""
    id: int
    portfolio_id: int
    date: date
    instrument_name: str
    net_eur: float               # netto convertito in EUR (solo display)
    covered_by_date: date        # data dell'import broker/manuale che lo copre


class DeduplicateResult(BaseModel):
    deleted: int
    removed: List[DividendDuplicate]


# ── Coupon schedule (certificati) ─────────────────────────────────────────────

class CouponCreate(BaseModel):
    instrument_id: int
    payment_date: date
    observation_date: Optional[_Date] = None
    amount_per_unit: float = Field(gt=0)   # per unità, valuta strumento
    coupon_type: CouponType = CouponType.CONDITIONAL
    memory_effect: bool = False
    notes: Optional[str] = None

class CouponUpdate(BaseModel):
    payment_date: Optional[_Date] = None
    observation_date: Optional[_Date] = None
    amount_per_unit: Optional[float] = Field(default=None, gt=0)
    coupon_type: Optional[CouponType] = None
    memory_effect: Optional[bool] = None
    notes: Optional[str] = None

class CouponOut(BaseModel):
    id: int
    instrument_id: int
    payment_date: date
    observation_date: Optional[date]
    amount_per_unit: float
    coupon_type: CouponType
    memory_effect: bool
    status: CouponStatus
    dividend_event_id: Optional[int]
    notes: Optional[str]
    model_config = {"from_attributes": True}

class UpcomingCoupon(BaseModel):
    """Riga del calendario "Prossime Cedole" (pagina Dividendi): cedola PLANNED
    di uno strumento in posizione, con stima del lordo sulla quantità detenuta."""
    id: int
    instrument_id: int
    ticker: str
    name: str
    currency: str
    payment_date: date
    observation_date: Optional[date]
    amount_per_unit: float
    coupon_type: CouponType
    memory_effect: bool
    quantity: float               # quantità detenuta (nei portafogli filtrati)
    estimated_total: float        # lordo stimato = amount_per_unit × quantity (valuta strumento)
    estimated_total_eur: float    # convertito all'ultimo cambio noto

class CouponConfirm(BaseModel):
    """Conferma di pagamento: il lordo effettivo può differire dal piano
    (es. cedole in memoria recuperate). Le tasse, se non fornite, sono
    stimate al 26% (imposta sostitutiva certificati)."""
    portfolio_id: int
    gross_amount: float = Field(gt=0)               # LORDO totale, valuta strumento
    date: Optional[_Date] = None                    # default: payment_date del piano
    tax_amount: Optional[float] = Field(default=None, ge=0)  # override manuale
    # Compensazione minusvalenze: imposta assorbita dallo zainetto, netto = lordo.
    minus_compensation: bool = False


class DividendMinusUpdate(BaseModel):
    """Toggle retroattivo della compensazione minusvalenza su un incasso
    (solo CERT_COUPON). OFF ricalcola la stima standard delle imposte."""
    minus_compensation: bool


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


class ClosedPositionRow(BaseModel):
    """Posizione interamente chiusa (quantità netta ≈ 0, con almeno una vendita)."""
    instrument_id: int
    ticker: str
    name: str
    isin: Optional[str]
    currency: str
    quantity: float             # quantità totale movimentata (= venduta)
    avg_buy_price: float        # prezzo medio d'acquisto, EUR
    avg_sell_price: float       # prezzo medio di vendita, EUR
    buy_value: float            # controvalore d'acquisto totale (prezzo × qtà), EUR
    sell_value: float           # controvalore di vendita totale (prezzo × qtà), EUR
    realized_pnl: float         # EUR, LORDO di tasse (netto commissioni)
    realized_pnl_pct: float
    realized_pnl_net: float     # EUR, al netto della stima imposta capital gain (26%/12,5%)
    current_price: Optional[float] = None   # prezzo attuale, EUR (None se non disponibile)
    current_value: Optional[float] = None   # valore ipotetico oggi = prezzo × quantità venduta, EUR
    first_buy_date: Optional[date] = None
    last_sell_date: Optional[date] = None


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
    # Variazione di mercato sul periodo mostrato (EUR e %, al netto di
    # versamenti/prelievi nella finestra). None quando i punti sono < 2.
    change: Optional[float] = None
    change_pct: Optional[float] = None


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
    total_ytd: float          # netto
    total_all_time: float     # netto
    total_gross: float = 0.0  # lordo
    total_tax: float = 0.0    # tasse (estera + italiana)
    avg_yield_on_cost: float

class DividendProjection(BaseModel):
    month: str
    amount: float

class MonthlyDividend(BaseModel):
    month: str
    amount: float           # totale netto (dividendi + cedole)
    dividends: float = 0.0  # netto da DIVIDEND
    coupons: float = 0.0    # netto da COUPON + CERT_COUPON


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
    # Ritenuta estera reale quando il file la fornisce (es. Fineco "Movimenti
    # conto", Trade Republic). Sui dividendi: price=LORDO, foreign_tax=ritenuta
    # estera, fees=imposta italiana. Default 0 → comportamento invariato.
    foreign_tax: float = 0.0
    # Avviso non bloccante mostrato in anteprima (es. vendita senza acquisto
    # corrispondente → posizione negativa). None = nessun problema.
    warning: Optional[str] = None
    # Riga riconosciuta ma da NON importare di default (es. trasferimento/cambio
    # denominativo titoli Mediolanum). Mostrata in anteprima ed esclusa dall'import;
    # l'utente può comunque abilitarla. Il backend la salta per sicurezza.
    excluded: bool = False

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
    # Solo in modalità "a versamenti" (money-weighted): guadagno in € sul periodo
    # e IRR annualizzato. In modalità TWR restano None.
    gain_eur: Optional[float] = None
    irr: Optional[float] = None

class BenchmarkHolding(BaseModel):
    instrument_id: int
    ticker: str
    name: str

class BenchmarkChartResponse(BaseModel):
    series: List[BenchmarkSeries]
    holdings: List[BenchmarkHolding] = []   # titoli del portafoglio (per i checkbox what-if)


# ── Admin ─────────────────────────────────────────────────────────────────────

class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


# ── Security / access log ─────────────────────────────────────────────────────

class LoginAttemptOut(BaseModel):
    id: int
    identifier: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    blocked: bool
    created_at: datetime
    model_config = {"from_attributes": True}

class LockoutEntry(BaseModel):
    type: str          # "ip" | "identifier"
    value: str
    fail_count: int

class SecurityStatus(BaseModel):
    max_attempts: int
    lockout_minutes: int
    locked: List[LockoutEntry]

class ClearLockout(BaseModel):
    ip_address: Optional[str] = None
    identifier: Optional[str] = None
