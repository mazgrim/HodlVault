from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
import math

router = APIRouter()


# ── Compound Interest ─────────────────────────────────────────────────────────

class CompoundInput(BaseModel):
    initial: float
    periodic: float = 0.0
    frequency: str = "monthly"   # monthly | annual
    rate_pct: float
    years: int
    inflation_pct: float = 0.0   # 0 = nominal only

class CompoundYearRow(BaseModel):
    year: int
    invested: float
    value: float
    gains: float
    real_value: float            # value deflated to today's purchasing power

class CompoundResult(BaseModel):
    final_value: float
    total_invested: float
    total_gains: float
    real_final_value: float      # final value in today's purchasing power
    rows: List[CompoundYearRow]


@router.post("/compound", response_model=CompoundResult)
def compound_interest(data: CompoundInput):
    rate = data.rate_pct / 100
    periods_per_year = 12 if data.frequency == "monthly" else 1
    rate_per_period = rate / periods_per_year
    periods = data.years * periods_per_year
    infl = data.inflation_pct / 100

    rows = []
    value = data.initial
    invested = data.initial

    for p in range(1, periods + 1):
        value = value * (1 + rate_per_period) + data.periodic
        invested += data.periodic
        if p % periods_per_year == 0:
            year = p // periods_per_year
            real_value = value / ((1 + infl) ** year) if infl else value
            rows.append(CompoundYearRow(
                year=year,
                invested=round(invested, 2),
                value=round(value, 2),
                gains=round(value - invested, 2),
                real_value=round(real_value, 2),
            ))

    real_final = value / ((1 + infl) ** data.years) if infl else value

    return CompoundResult(
        final_value=round(value, 2),
        total_invested=round(invested, 2),
        total_gains=round(value - invested, 2),
        real_final_value=round(real_final, 2),
        rows=rows,
    )


# ── FIRE Calculator ───────────────────────────────────────────────────────────

class FireInput(BaseModel):
    annual_expenses: float
    current_wealth: float
    annual_savings: float
    expected_return_pct: float = 7.0
    swr_pct: float = 4.0
    inflation_pct: float = 2.0

class FireYearRow(BaseModel):
    year: int
    wealth: float
    target: float

class FireResult(BaseModel):
    fire_target: float
    years_to_fire: int
    projected_year: int
    rows: List[FireYearRow]


@router.post("/fire", response_model=FireResult)
def fire_calculator(data: FireInput):
    from datetime import datetime
    real_return = (1 + data.expected_return_pct / 100) / (1 + data.inflation_pct / 100) - 1
    fire_target = data.annual_expenses / (data.swr_pct / 100)
    wealth = data.current_wealth
    rows = []
    current_year = datetime.now().year

    for year in range(1, 101):
        wealth = wealth * (1 + real_return) + data.annual_savings
        # Inflate target
        inflated_target = fire_target * ((1 + data.inflation_pct / 100) ** year)
        rows.append(FireYearRow(year=year, wealth=round(wealth, 2), target=round(inflated_target, 2)))
        if wealth >= inflated_target:
            return FireResult(
                fire_target=round(fire_target, 2),
                years_to_fire=year,
                projected_year=current_year + year,
                rows=rows,
            )

    return FireResult(
        fire_target=round(fire_target, 2),
        years_to_fire=100,
        projected_year=current_year + 100,
        rows=rows,
    )


# ── PAC vs Lump Sum ───────────────────────────────────────────────────────────

# Contribution interval in months, keyed by PAC frequency.
_PAC_INTERVAL = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}

class PacInput(BaseModel):
    total_amount: float
    years: int
    expected_return_pct: float
    frequency: str = "monthly"   # monthly | quarterly | semiannual | annual

class PacResult(BaseModel):
    lump_sum_final: float
    lump_sum_return_total_pct: float
    lump_sum_cagr_pct: float
    pac_final: float
    pac_return_total_pct: float
    pac_cagr_pct: float
    num_contributions: int
    contribution_amount: float
    chart: List[dict]


@router.post("/pac-vs-lumpsum", response_model=PacResult)
def pac_vs_lumpsum(data: PacInput):
    r = data.expected_return_pct / 100
    monthly_r = r / 12
    n = data.years * 12
    interval = _PAC_INTERVAL.get(data.frequency, 1)
    # years*12 is always divisible by 1/3/6/12, so contributions split cleanly.
    num_contributions = n // interval if interval else 0
    contribution = data.total_amount / num_contributions if num_contributions else 0.0

    # Simulate month by month so the headline figures and the chart share the
    # exact same compounding (monthly). The PAC contributes at the start of each
    # period (every `interval` months); the lump sum is fully invested at t=0.
    chart = []
    ls_val = data.total_amount
    pac_val = 0.0
    for month in range(1, n + 1):
        if (month - 1) % interval == 0:
            pac_val += contribution
        ls_val = ls_val * (1 + monthly_r)
        pac_val = pac_val * (1 + monthly_r)
        if month % 12 == 0:
            chart.append({
                "year": month // 12,
                "lump_sum": round(ls_val, 2),
                "pac": round(pac_val, 2),
            })

    lump_final = ls_val
    pac_final = pac_val

    def cagr(final, invested, years):
        if years == 0 or invested == 0:
            return 0.0
        return round(((final / invested) ** (1 / years) - 1) * 100, 2)

    def total_pct(final):
        if data.total_amount == 0:
            return 0.0
        return round((final / data.total_amount - 1) * 100, 2)

    return PacResult(
        lump_sum_final=round(lump_final, 2),
        lump_sum_return_total_pct=total_pct(lump_final),
        lump_sum_cagr_pct=cagr(lump_final, data.total_amount, data.years),
        pac_final=round(pac_final, 2),
        pac_return_total_pct=total_pct(pac_final),
        pac_cagr_pct=cagr(pac_final, data.total_amount, data.years),
        num_contributions=num_contributions,
        contribution_amount=round(contribution, 2),
        chart=chart,
    )


# ── Inflation Calculator ──────────────────────────────────────────────────────

class InflationInput(BaseModel):
    amount: float
    start_year: int
    end_year: int
    inflation_pct: float = 2.0

class InflationResult(BaseModel):
    real_value: float
    purchasing_power_lost_pct: float
    required_value: float          # amount needed at end_year to keep purchasing power
    chart: List[dict]


@router.post("/inflation", response_model=InflationResult)
def inflation_calculator(data: InflationInput):
    years = data.end_year - data.start_year
    if years < 0:
        years = 0
    rate = data.inflation_pct / 100
    real_value = data.amount / ((1 + rate) ** years)
    lost_pct = (1 - real_value / data.amount) * 100 if data.amount else 0.0
    required_value = data.amount * ((1 + rate) ** years)

    chart = []
    for y in range(years + 1):
        chart.append({
            "year": data.start_year + y,
            "value": round(data.amount / ((1 + rate) ** y), 2),
        })

    return InflationResult(
        real_value=round(real_value, 2),
        purchasing_power_lost_pct=round(lost_pct, 2),
        required_value=round(required_value, 2),
        chart=chart,
    )
