"""
Config API router for MultiStrategy Portfolio
Endpoints for managing per-strategy configuration (trading mode, etc.)
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional
import logging

from ..database import get_db
from ..models import StrategyConfig

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

    import os
    mode = config.trading_mode if config else "PAPER"
    return {"strategy_name": strategy_name, "trading_mode": mode}