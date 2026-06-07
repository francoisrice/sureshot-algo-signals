"""
Portfolio state schemas for request/response validation
"""

from pydantic import BaseModel
from typing import Optional, Dict, List
from datetime import datetime


class InitializeRequest(BaseModel):
    """Request schema for initializing portfolios"""
    strategies: List[str]
    total_capital: float
    allocation_method: str = "equal_weight"


class PortfolioStateResponse(BaseModel):
    """Response schema for portfolio state data"""
    id: int
    strategy_name: str
    cash: float
    allocated_capital: float
    initial_cash: float
    total_value: float
    invested: bool
    total_return: Optional[float]
    total_return_pct: Optional[float]
    last_updated: datetime

    class Config:
        from_attributes = True


class AllocationResponse(BaseModel):
    """Response schema for capital allocation across strategies"""
    total_cash: float
    total_allocated: float
    total_locked: float
    allocations: Dict[str, Dict[str, float]]  # {strategy_name: {allocated, locked, score}}
    last_rebalance: Optional[datetime]


class RotateStrategiesRequest(BaseModel):
    """Request schema for rotating which strategies trade LIVE vs PAPER.
    Provide strategy_names for an explicit list, or top_n to auto-select
    the best performers by selection_metric. One of the two must be set.
    """
    strategy_names: Optional[List[str]] = None
    top_n: Optional[int] = None
    selection_metric: str = "total_return_pct"  # column on PortfolioState; used only with top_n
    reason: Optional[str] = None
