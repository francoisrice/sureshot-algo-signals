"""
Portfolio state schemas for request/response validation
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PortfolioStateUpdate(BaseModel):
    """Request schema for updating portfolio state"""
    strategy_name: str
    cash: float
    initial_cash: float
    invested: bool


class PortfolioStateResponse(BaseModel):
    """Response schema for portfolio state data"""
    id: int
    strategy_name: str
    cash: float
    initial_cash: float
    total_value: float
    invested: bool
    total_return: Optional[float]
    total_return_pct: Optional[float]
    last_updated: datetime

    class Config:
        orm_mode = True
