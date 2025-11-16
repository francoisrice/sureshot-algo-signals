"""
Portfolio API router
Endpoints for managing portfolio state per strategy
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List
import logging

from ..database import get_db
from ..models import PortfolioState, Position
from ..schemas import PortfolioStateUpdate, PortfolioStateResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("", response_model=PortfolioStateResponse)
async def upsert_portfolio_state(portfolio: PortfolioStateUpdate, db: Session = Depends(get_db)):
    """Create or update portfolio state for a strategy"""
    try:
        db_portfolio = db.query(PortfolioState).filter(
            PortfolioState.strategy_name == portfolio.strategy_name
        ).first()

        # Get positions for this strategy to calculate total value
        positions = db.query(Position).filter(
            Position.strategy_name == portfolio.strategy_name
        ).all()

        total_position_value = sum(p.market_value or 0 for p in positions)
        total_value = portfolio.cash + total_position_value
        total_return = total_value - portfolio.initial_cash
        total_return_pct = (total_return / portfolio.initial_cash) * 100 if portfolio.initial_cash > 0 else 0

        if db_portfolio:
            # Update existing
            db_portfolio.cash = portfolio.cash
            db_portfolio.initial_cash = portfolio.initial_cash
            db_portfolio.invested = portfolio.invested
            db_portfolio.total_value = total_value
            db_portfolio.total_return = total_return
            db_portfolio.total_return_pct = total_return_pct
        else:
            # Create new
            db_portfolio = PortfolioState(
                strategy_name=portfolio.strategy_name,
                cash=portfolio.cash,
                initial_cash=portfolio.initial_cash,
                invested=portfolio.invested,
                total_value=total_value,
                total_return=total_return,
                total_return_pct=total_return_pct
            )
            db.add(db_portfolio)

        db.commit()
        db.refresh(db_portfolio)

        logger.info(f"Portfolio state updated: {portfolio.strategy_name}")

        return db_portfolio
    except Exception as e:
        logger.error(f"Error upserting portfolio state: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_name}", response_model=PortfolioStateResponse)
async def get_portfolio_state(strategy_name: str, db: Session = Depends(get_db)):
    """Get portfolio state for a specific strategy"""
    db_portfolio = db.query(PortfolioState).filter(
        PortfolioState.strategy_name == strategy_name
    ).first()

    if not db_portfolio:
        raise HTTPException(status_code=404, detail="Portfolio state not found")

    return db_portfolio


@router.get("", response_model=List[PortfolioStateResponse])
async def get_all_portfolio_states(db: Session = Depends(get_db)):
    """Get portfolio state for all strategies"""
    portfolios = db.query(PortfolioState).all()
    return portfolios


@router.get("/{strategy_name}/invested")
async def get_invested_status(strategy_name: str, db: Session = Depends(get_db)):
    """Get invested status for a specific strategy"""
    db_portfolio = db.query(PortfolioState).filter(
        PortfolioState.strategy_name == strategy_name
    ).first()

    if not db_portfolio:
        raise HTTPException(status_code=404, detail="Portfolio state not found")

    return {"strategy_name": strategy_name, "invested": db_portfolio.invested}
