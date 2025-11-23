"""
Order schemas for request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict
from datetime import datetime


class OrderCreate(BaseModel):
    """Request schema for creating a new order"""
    strategy_name: str = Field(..., description="Strategy identifier (e.g., SPXL)")
    symbol: str = Field(..., description="Trading symbol")
    order_type: str = Field(..., description="BUY or SELL")
    quantity: float = Field(..., gt=0, description="Number of shares")
    price: Optional[float] = Field(None, description="Execution price")
    conid: Optional[int] = Field(None, description="IBKR contract ID")
    metadata: Optional[Dict] = Field(None, description="Additional order metadata")


class OrderStatusUpdate(BaseModel):
    """Request schema for updating order status"""
    status: str = Field(..., description="Order status: PENDING, EXECUTED, FAILED")
    ibkr_order_id: Optional[str] = Field(None, description="IBKR order ID")
    execution_price: Optional[float] = Field(None, description="Actual execution price")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class OrderResponse(BaseModel):
    """Response schema for order data"""
    id: int
    strategy_name: str
    symbol: str
    order_type: str
    quantity: float
    price: Optional[float]
    order_value: Optional[float]
    status: str
    trading_mode: Optional[str]
    timestamp: datetime
    ibkr_order_id: Optional[str]
    execution_timestamp: Optional[datetime]

    class Config:
        orm_mode = True


class TradeRequest(BaseModel):
    """Request schema for buy_all/sell_all operations"""
    strategy_name: str = Field(..., description="Strategy identifier (e.g., SPXL)")
    symbol: str = Field(..., description="Trading symbol")
    price: float = Field(..., gt=0, description="Current market price")


class TradeResponse(BaseModel):
    """Response schema for buy_all/sell_all operations"""
    order_id: int
    strategy_name: str
    symbol: str
    order_type: str
    quantity: float
    price: float
    order_value: float
    remaining_cash: float
    invested: bool
