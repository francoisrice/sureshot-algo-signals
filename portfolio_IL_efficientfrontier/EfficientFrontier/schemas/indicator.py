"""
Indicator schemas for request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class IndicatorCreate(BaseModel):
    """Request schema for recording an indicator value"""
    strategy_name: str
    symbol: str
    indicator_type: str = Field(..., description="Type: SMA, EMA, RSI, etc.")
    period: Optional[int] = Field(None, description="Indicator period (e.g., 252 for SMA)")
    timeframe: Optional[str] = Field(None, description="Timeframe: 1d, 1h, 5m")
    value: float


class IndicatorResponse(BaseModel):
    """Response schema for indicator data"""
    id: int
    strategy_name: str
    symbol: str
    indicator_type: str
    period: Optional[int]
    timeframe: Optional[str]
    value: float
    timestamp: datetime

    class Config:
        orm_mode = True
