"""
Config API router for MultiStrategy Portfolio
Endpoints for managing per-strategy configuration (trading mode, etc.)
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import logging

from ..database import get_db
from ..models import StrategyConfig, StrategyModeHistory, PortfolioState
from ..schemas import RotateStrategiesRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


@router.post("/{strategy_name}/trading-mode")
def set_trading_mode(
    strategy_name: str,
    trading_mode: str = "PAPER",
    db: Session = Depends(get_db)
):
    """Set the trading mode for a strategy to PAPER or LIVE."""
    trading_mode = trading_mode.upper()
    if trading_mode not in ("PAPER", "LIVE"):
        logger.error(f"Invalid trading mode attempted: {trading_mode} for {strategy_name}")
        return {"strategy_name": strategy_name, "trading_mode": None, "error": f"trading_mode must be PAPER or LIVE, got: {trading_mode}"}

    existing = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == strategy_name
    ).first()

    if existing:
        existing.trading_mode = trading_mode
    else:
        db.add(StrategyConfig(strategy_name=strategy_name, trading_mode=trading_mode))

    db.commit()
    return {"strategy_name": strategy_name, "trading_mode": trading_mode}


@router.get("/{strategy_name}/trading-mode")
def get_trading_mode(
    strategy_name: str,
    db: Session = Depends(get_db)
):
    """Get the trading mode for a strategy."""
    config = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == strategy_name
    ).first()

    mode = config.trading_mode if config else "PAPER"
    return {"strategy_name": strategy_name, "trading_mode": mode}


@router.post("/rotate-live-strategies")
def rotate_live_strategies(
    request: RotateStrategiesRequest,
    db: Session = Depends(get_db)
):
    """
    Atomically set which strategies trade LIVE; all others become PAPER.

    Provide strategy_names for an explicit list, or top_n to auto-select
    the best performers ranked by selection_metric (default: total_return_pct).
    Changes persist in the database across restarts — this endpoint is the
    sole source of truth for LIVE/PAPER assignment.
    """
    if not request.strategy_names and not request.top_n:
        raise HTTPException(
            status_code=400,
            detail="Provide strategy_names (explicit list) or top_n (auto-select by performance)."
        )

    # Auto-select top N by performance metric
    if request.top_n and not request.strategy_names:
        valid_metrics = {"total_return_pct", "total_return", "total_value"}
        if request.selection_metric not in valid_metrics:
            raise HTTPException(
                status_code=400,
                detail=f"selection_metric must be one of {valid_metrics}"
            )
        portfolios = db.query(PortfolioState).all()
        sorted_portfolios = sorted(
            portfolios,
            key=lambda p: getattr(p, request.selection_metric) or 0.0,
            reverse=True
        )
        live_set = {p.strategy_name for p in sorted_portfolios[:request.top_n]}
    else:
        live_set = set(request.strategy_names)

    all_configs = db.query(StrategyConfig).all()
    known_strategies = {c.strategy_name for c in all_configs}

    # Ensure every strategy in live_set has a StrategyConfig row
    for name in live_set:
        if name not in known_strategies:
            db.add(StrategyConfig(strategy_name=name, trading_mode="PAPER"))
            all_configs = db.query(StrategyConfig).all()  # refresh after add

    promoted, demoted, unchanged = [], [], []
    triggered_by = "performance" if request.top_n and not request.strategy_names else "manual"

    for config in db.query(StrategyConfig).all():
        new_mode = "LIVE" if config.strategy_name in live_set else "PAPER"
        if new_mode != config.trading_mode:
            db.add(StrategyModeHistory(
                strategy_name=config.strategy_name,
                from_mode=config.trading_mode,
                to_mode=new_mode,
                reason=request.reason,
                triggered_by=triggered_by,
            ))
            config.trading_mode = new_mode
            (promoted if new_mode == "LIVE" else demoted).append(config.strategy_name)
        else:
            unchanged.append(config.strategy_name)

    db.commit()

    logger.info(
        f"Strategy rotation ({triggered_by}): promoted={promoted} demoted={demoted} "
        f"reason='{request.reason}'"
    )

    return {
        "promoted_to_live": promoted,
        "demoted_to_paper": demoted,
        "unchanged": unchanged,
        "triggered_by": triggered_by,
        "reason": request.reason,
        "timestamp": datetime.utcnow(),
    }


@router.get("/mode-history")
def get_mode_history(
    strategy_name: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Audit trail of all LIVE/PAPER transitions."""
    query = db.query(StrategyModeHistory).order_by(StrategyModeHistory.timestamp.desc())
    if strategy_name:
        query = query.filter(StrategyModeHistory.strategy_name == strategy_name)
    records = query.limit(limit).all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "strategy_name": r.strategy_name,
            "from_mode": r.from_mode,
            "to_mode": r.to_mode,
            "reason": r.reason,
            "triggered_by": r.triggered_by,
        }
        for r in records
    ]


@router.get("/all-modes")
def get_all_trading_modes(db: Session = Depends(get_db)):
    """Current LIVE/PAPER assignment for every known strategy."""
    configs = db.query(StrategyConfig).all()
    return [
        {"strategy_name": c.strategy_name, "trading_mode": c.trading_mode, "last_updated": c.last_updated}
        for c in configs
    ]