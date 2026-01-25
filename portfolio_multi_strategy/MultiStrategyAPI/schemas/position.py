"""
Position schemas for request/response validation
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PositionUpdate(BaseModel):
    """Request schema for creating/updating a position"""
    strategy_name: str
    symbol: str
    quantity: float
    avg_price: float
    current_price: Optional[float] = None


class PositionResponse(BaseModel):
    """Response schema for position data"""
    id: int
    strategy_name: str
    symbol: str
    quantity: float
    avg_price: float
    current_price: Optional[float]
    market_value: Optional[float]
    unrealized_pnl: Optional[float]
    last_updated: datetime

    class Config:
        from_attributes = True
