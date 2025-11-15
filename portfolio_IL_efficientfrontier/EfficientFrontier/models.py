"""
Database models for EfficientFrontier API
SQLAlchemy ORM models for orders, positions, portfolio state, and indicators
"""

from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Order(Base):
    """Order execution records"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, index=True, nullable=False)  # e.g., "SPXL", "NVDL"
    symbol = Column(String, index=True, nullable=False)
    order_type = Column(String, nullable=False)  # "BUY" or "SELL"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # Execution price
    order_value = Column(Float, nullable=True)  # Total value
    conid = Column(Integer, nullable=True)  # IBKR contract ID
    ibkr_order_id = Column(String, nullable=True)  # IBKR order ID
    status = Column(String, default="PENDING")  # PENDING, EXECUTED, FAILED
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    execution_timestamp = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
    order_metadata = Column(JSON, nullable=True)  # Additional order details


class Position(Base):
    """Current portfolio positions per strategy"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, index=True, nullable=False)
    symbol = Column(String, index=True, nullable=False)
    quantity = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioState(Base):
    """Portfolio state snapshot per strategy"""
    __tablename__ = "portfolio_state"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, index=True, nullable=False, unique=True)
    cash = Column(Float, nullable=False)
    initial_cash = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    invested = Column(Boolean, default=False)
    total_return = Column(Float, nullable=True)
    total_return_pct = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Indicator(Base):
    """Technical indicators state (e.g., SMA values)"""
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, index=True, nullable=False)
    symbol = Column(String, index=True, nullable=False)
    indicator_type = Column(String, nullable=False)  # "SMA", "EMA", etc.
    period = Column(Integer, nullable=True)
    timeframe = Column(String, nullable=True)  # "1d", "1h", "5m"
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
