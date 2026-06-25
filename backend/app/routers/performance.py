from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user
from ..services.calculations import PerformanceCalculator

router = APIRouter()


@router.get("/kpis", response_model=schemas.PerformanceMetrics)
def performance_metrics(
    portfolio_id: Optional[int] = Query(None),
    benchmark: str = Query("SWDA.MI"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = PerformanceCalculator(db, current_user.id)
    return calc.metrics(portfolio_id, benchmark)


@router.get("/monthly-returns", response_model=List[schemas.MonthlyReturn])
def monthly_returns(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = PerformanceCalculator(db, current_user.id)
    return calc.monthly_returns(portfolio_id)


@router.get("/drawdown", response_model=List[schemas.DrawdownPoint])
def drawdown_series(
    portfolio_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = PerformanceCalculator(db, current_user.id)
    return calc.drawdown_series(portfolio_id)


@router.get("/cumulative", response_model=schemas.PortfolioChartResponse)
def cumulative_return(
    portfolio_id: Optional[int] = Query(None),
    benchmark: str = Query("SWDA.MI"),
    period: str = Query("1Y"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    calc = PerformanceCalculator(db, current_user.id)
    return calc.cumulative_chart(portfolio_id, benchmark, period)
