"""
Database models for MultiStrategy Portfolio API
SQLAlchemy ORM models for orders, positions, portfolio state, and capital allocation
"""

from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Order(Base):
    """Order execution records"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, index=True, nullable=False)
    symbol = Column(String, index=True, nullable=False)
    order_type = Column(String, nullable=False)  # "BUY" or "SELL"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    order_value = Column(Float, nullable=True)
    conid = Column(Integer, nullable=True)
    ibkr_order_id = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    trading_mode = Column(String, default="PAPER")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    execution_timestamp = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
    order_metadata = Column(JSON, nullable=True)


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
    allocated_capital = Column(Float, nullable=False)  # Capital allocated to this strategy
    initial_cash = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    invested = Column(Boolean, default=False)
    position_locked = Column(Boolean, default=False)  # True when strategy has open position
    total_return = Column(Float, nullable=True)
    total_return_pct = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AllocationHistory(Base):
    """Track capital allocation changes over time"""
    __tablename__ = "allocation_history"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    total_capital = Column(Float, nullable=False)
    allocations = Column(JSON, nullable=False)  # {strategy_name: {allocated, score, locked}}
    rebalance_reason = Column(String, nullable=True)
