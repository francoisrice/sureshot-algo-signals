"""
Portfolio API router for MultiStrategy Portfolio
Endpoints for managing portfolio state and capital allocation
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime

from ..database import get_db
from ..models import PortfolioState, Position, AllocationHistory
from ..schemas import PortfolioStateResponse, AllocationResponse
from ..allocation import CapitalAllocator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


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


@router.post("/initialize")
async def initialize_portfolios(
    strategies: List[str],
    total_capital: float,
    allocation_method: str = "equal_weight",
    db: Session = Depends(get_db)
):
    """
    Initialize portfolio states for multiple strategies

    Args:
        strategies: List of strategy names
        total_capital: Total capital to allocate across strategies
        allocation_method: "equal_weight" or "risk_adjusted"
        db: Database session

    Returns:
        Dict with allocation details for each strategy
    """
    try:
        allocator = CapitalAllocator()

        # Calculate initial allocations
        allocations = allocator.allocate_capital(
            db=db,
            total_capital=total_capital,
            strategies=strategies,
            method=allocation_method
        )

        # Create or update portfolio states
        created_portfolios = []
        for strategy_name, allocated_capital in allocations.items():
            # Check if portfolio already exists
            portfolio = db.query(PortfolioState).filter(
                PortfolioState.strategy_name == strategy_name
            ).first()

            if portfolio:
                # Update existing portfolio
                portfolio.allocated_capital = allocated_capital
                portfolio.cash = allocated_capital
                portfolio.initial_cash = allocated_capital
                portfolio.total_value = allocated_capital
                portfolio.last_updated = datetime.utcnow()
                logger.info(f"Updated portfolio for {strategy_name}: ${allocated_capital:,.2f}")
            else:
                # Create new portfolio
                portfolio = PortfolioState(
                    strategy_name=strategy_name,
                    cash=allocated_capital,
                    allocated_capital=allocated_capital,
                    initial_cash=allocated_capital,
                    total_value=allocated_capital,
                    invested=False,
                    position_locked=False,
                    total_return=0.0,
                    total_return_pct=0.0
                )
                db.add(portfolio)
                logger.info(f"Created portfolio for {strategy_name}: ${allocated_capital:,.2f}")

            created_portfolios.append({
                "strategy_name": strategy_name,
                "allocated_capital": allocated_capital,
                "cash": allocated_capital
            })

        # Record allocation history
        history = AllocationHistory(
            timestamp=datetime.utcnow(),
            total_capital=total_capital,
            allocations={s: {"allocated": allocations[s], "locked": False} for s in strategies},
            rebalance_reason=f"Initial allocation using {allocation_method}"
        )
        db.add(history)

        db.commit()

        logger.info(f"Initialized {len(created_portfolios)} portfolios with total capital ${total_capital:,.2f}")

        return {
            "total_capital": total_capital,
            "allocation_method": allocation_method,
            "portfolios": created_portfolios
        }

    except Exception as e:
        logger.error(f"Error initializing portfolios: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebalance")
async def rebalance_portfolio(
    total_capital: float,
    strategies: List[str],
    allocation_method: str = "risk_adjusted",
    db: Session = Depends(get_db)
):
    """
    Trigger portfolio rebalancing across strategies

    This endpoint reallocates capital based on strategy performance.
    Strategies with locked positions (currently invested) maintain their allocation.
    Only unlocked strategies (in cash) will have their capital redistributed.

    Args:
        total_capital: Total capital available for allocation
        strategies: List of strategy names to include in rebalancing
        allocation_method: "equal_weight" or "risk_adjusted"
        db: Database session

    Returns:
        Allocation details showing old vs new allocations per strategy
    """
    try:
        allocator = CapitalAllocator()

        # Perform rebalancing
        allocation_details = allocator.rebalance_portfolio(
            db=db,
            total_capital=total_capital,
            strategies=strategies,
            method=allocation_method
        )

        # Update portfolio cash for unlocked strategies
        for strategy_name, details in allocation_details.items():
            if not details['locked']:
                portfolio = db.query(PortfolioState).filter(
                    PortfolioState.strategy_name == strategy_name
                ).first()

                if portfolio:
                    # Update cash to match new allocation (only for unlocked strategies)
                    cash_change = details['change']
                    portfolio.cash += cash_change
                    logger.info(f"Rebalanced {strategy_name}: ${details['previous']:,.2f} -> ${details['allocated']:,.2f} (change: ${cash_change:+,.2f})")

        db.commit()

        logger.info(f"Portfolio rebalanced using {allocation_method}: {allocation_details}")

        return {
            "total_capital": total_capital,
            "allocation_method": allocation_method,
            "rebalance_timestamp": datetime.utcnow(),
            "allocation_details": allocation_details
        }

    except Exception as e:
        logger.error(f"Error rebalancing portfolio: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/allocation/current", response_model=AllocationResponse)
async def get_current_allocation(db: Session = Depends(get_db)):
    """
    Get current capital allocation across all strategies

    Returns:
        Summary of total capital, allocations, and locked positions
    """
    try:
        portfolios = db.query(PortfolioState).all()

        if not portfolios:
            raise HTTPException(status_code=404, detail="No portfolios found")

        total_cash = sum(p.cash for p in portfolios)
        total_allocated = sum(p.allocated_capital for p in portfolios)
        total_locked = sum(p.allocated_capital for p in portfolios if p.position_locked)

        allocations = {}
        for portfolio in portfolios:
            allocations[portfolio.strategy_name] = {
                "allocated": portfolio.allocated_capital,
                "cash": portfolio.cash,
                "locked": portfolio.position_locked,
                "invested": portfolio.invested,
                "total_value": portfolio.total_value
            }

        # Get last rebalance timestamp
        last_rebalance = db.query(AllocationHistory).order_by(
            AllocationHistory.timestamp.desc()
        ).first()

        return AllocationResponse(
            total_cash=total_cash,
            total_allocated=total_allocated,
            total_locked=total_locked,
            allocations=allocations,
            last_rebalance=last_rebalance.timestamp if last_rebalance else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current allocation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/allocation/history")
async def get_allocation_history(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Get historical allocation changes

    Args:
        limit: Maximum number of history records to return
        db: Database session

    Returns:
        List of allocation history records
    """
    try:
        history = db.query(AllocationHistory).order_by(
            AllocationHistory.timestamp.desc()
        ).limit(limit).all()

        return [
            {
                "timestamp": h.timestamp,
                "total_capital": h.total_capital,
                "allocations": h.allocations,
                "rebalance_reason": h.rebalance_reason
            }
            for h in history
        ]

    except Exception as e:
        logger.error(f"Error getting allocation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
