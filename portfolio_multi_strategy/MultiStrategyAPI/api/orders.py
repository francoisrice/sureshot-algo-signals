"""
Order API router for MultiStrategy Portfolio
Endpoints for creating and managing order records with capital allocation support
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging
import os

from ..database import get_db
from ..models import Order, PortfolioState, Position
from ..schemas import OrderCreate, OrderStatusUpdate, OrderResponse, TradeRequest, TradeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


def get_trading_mode():
    """Get current trading mode from environment"""
    return os.getenv("TRADING_MODE", "PAPER").upper()


def execute_paper_trade(order_type: str, symbol: str, quantity: float, price: float):
    """
    Execute paper trade (just log it, no actual broker call)

    Returns:
        dict: Paper trade execution details
    """
    logger.info(f"PAPER TRADE: {order_type} {quantity} {symbol} @ ${price:.2f}")
    return {
        "status": "EXECUTED",
        "execution_timestamp": datetime.utcnow(),
        "ibkr_order_id": None
    }


def execute_live_trade(order_type: str, symbol: str, quantity: float, price: float, conid: int = None):
    """
    Execute live trade via IBKR client

    Args:
        order_type: BUY or SELL
        symbol: Trading symbol
        quantity: Number of shares
        price: Limit price
        conid: IBKR contract ID

    Returns:
        dict: Live trade execution details with IBKR order ID
    """
    try:
        from SureshotSDK.ibkr.automation.client import IBKRClient

        logger.info(f"LIVE TRADE: {order_type} {quantity} {symbol} @ ${price:.2f}")

        # Initialize IBKR client
        ibkr_client = IBKRClient()

        # Get contract ID if not provided
        if not conid:
            conid = ibkr_client.fetch_conid(symbol)
            if not conid:
                raise Exception(f"Could not fetch contract ID for {symbol}")

        # Place order based on type
        if order_type == "BUY":
            order_response = ibkr_client.place_order(
                conid=conid,
                quantity=quantity,
                side="BUY",
                order_type="LMT",
                price=price
            )
        else:  # SELL
            order_response = ibkr_client.place_order(
                conid=conid,
                quantity=quantity,
                side="SELL",
                order_type="LMT",
                price=price
            )

        # Extract order ID from response
        ibkr_order_id = order_response.get("orderId") if order_response else None

        if not ibkr_order_id:
            raise Exception("Failed to get IBKR order ID from response")

        logger.info(f"IBKR Order placed: {ibkr_order_id}")

        return {
            "status": "PENDING",  # Live orders start as PENDING until confirmed
            "execution_timestamp": None,  # Will be updated when order fills
            "ibkr_order_id": ibkr_order_id
        }

    except Exception as e:
        logger.error(f"Live trade execution failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute live trade: {str(e)}"
        )


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    """Create a new order"""
    try:
        # Calculate order value if price is provided
        order_value = None
        if order.price:
            order_value = order.quantity * order.price

        db_order = Order(
            strategy_name=order.strategy_name,
            symbol=order.symbol,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            order_value=order_value,
            conid=order.conid,
            order_metadata=order.metadata,
            status="PENDING"
        )

        db.add(db_order)
        db.commit()
        db.refresh(db_order)

        logger.info(f"Order created: {order.strategy_name} {order.order_type} {order.quantity} {order.symbol}")

        return db_order
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    status_update: OrderStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update order status (PENDING -> EXECUTED or FAILED)"""
    db_order = db.query(Order).filter(Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

    db_order.status = status_update.status
    if status_update.ibkr_order_id:
        db_order.ibkr_order_id = status_update.ibkr_order_id
    if status_update.execution_price:
        db_order.price = status_update.execution_price
        db_order.order_value = status_update.execution_price * db_order.quantity
    if status_update.error_message:
        db_order.error_message = status_update.error_message
    if status_update.status == "EXECUTED":
        db_order.execution_timestamp = datetime.utcnow()

    db.commit()
    db.refresh(db_order)

    logger.info(f"Order {order_id} status updated to {status_update.status}")

    return db_order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, db: Session = Depends(get_db)):
    """Get order by ID"""
    db_order = db.query(Order).filter(Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order


@router.get("", response_model=List[OrderResponse])
async def get_orders(
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get orders with optional filters"""
    query = db.query(Order)

    if strategy_name:
        query = query.filter(Order.strategy_name == strategy_name)
    if symbol:
        query = query.filter(Order.symbol == symbol)
    if status:
        query = query.filter(Order.status == status)

    orders = query.order_by(Order.timestamp.desc()).limit(limit).all()
    return orders


@router.post("/buy_all", response_model=TradeResponse, status_code=201)
async def buy_all(trade: TradeRequest, db: Session = Depends(get_db)):
    """
    Buy as many shares as possible with strategy's allocated capital

    Args:
        trade: TradeRequest with strategy_name, symbol, and current price
        db: Database session

    Returns:
        TradeResponse with order details and updated portfolio state
    """
    try:
        # Get or create portfolio state
        portfolio = db.query(PortfolioState).filter(
            PortfolioState.strategy_name == trade.strategy_name
        ).first()

        if not portfolio:
            raise HTTPException(
                status_code=404,
                detail=f"Portfolio not found for strategy {trade.strategy_name}. Create portfolio first."
            )

        # IMPORTANT: Use allocated_capital (not total cash) to determine buying power
        # This ensures each strategy only uses their allocated portion
        # available_cash = min(portfolio.cash, portfolio.allocated_capital)
        available_cash = portfolio.cash

        # Calculate shares to buy based on allocated capital
        shares_to_buy = int(available_cash // trade.price)

        if shares_to_buy <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient allocated capital. Available: ${available_cash:.2f}, Allocated: ${portfolio.allocated_capital:.2f}, Price: ${trade.price:.2f}"
            )

        total_cost = shares_to_buy * trade.price

        # Determine trading mode and execute trade
        trading_mode = get_trading_mode()

        if trading_mode == "PAPER":
            # Paper trade - just log it
            trade_result = execute_paper_trade("BUY", trade.symbol, shares_to_buy, trade.price)
        else:  # LIVE
            # Live trade - call IBKR
            trade_result = execute_live_trade("BUY", trade.symbol, shares_to_buy, trade.price)

        # Create order record
        order = Order(
            strategy_name=trade.strategy_name,
            symbol=trade.symbol,
            order_type="BUY",
            quantity=shares_to_buy,
            price=trade.price,
            order_value=total_cost,
            status=trade_result["status"],
            trading_mode=trading_mode,
            ibkr_order_id=trade_result["ibkr_order_id"],
            execution_timestamp=trade_result["execution_timestamp"]
        )
        db.add(order)

        # Update portfolio state
        portfolio.cash -= total_cost
        portfolio.invested = True
        portfolio.position_locked = True  # Lock position so it won't be rebalanced
        portfolio.total_value = portfolio.cash

        # Update or create position
        position = db.query(Position).filter(
            Position.strategy_name == trade.strategy_name,
            Position.symbol == trade.symbol
        ).first()

        if position:
            # Update average price
            total_shares = position.quantity + shares_to_buy
            total_cost_basis = (position.quantity * position.avg_price) + total_cost
            position.avg_price = total_cost_basis / total_shares
            position.quantity = total_shares
            position.current_price = trade.price
            position.market_value = total_shares * trade.price
        else:
            position = Position(
                strategy_name=trade.strategy_name,
                symbol=trade.symbol,
                quantity=shares_to_buy,
                avg_price=trade.price,
                current_price=trade.price,
                market_value=total_cost
            )
            db.add(position)

        # Update total portfolio value
        portfolio.total_value += position.market_value

        db.commit()
        db.refresh(order)

        logger.info(f"BUY_ALL executed: {trade.strategy_name} bought {shares_to_buy} {trade.symbol} @ ${trade.price:.2f} using allocated capital ${portfolio.allocated_capital:.2f}")

        return TradeResponse(
            order_id=order.id,
            strategy_name=trade.strategy_name,
            symbol=trade.symbol,
            order_type="BUY",
            quantity=shares_to_buy,
            price=trade.price,
            order_value=total_cost,
            allocated_capital=portfolio.allocated_capital,
            remaining_cash=portfolio.cash,
            invested=portfolio.invested
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in buy_all: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sell_all", response_model=TradeResponse, status_code=201)
async def sell_all(trade: TradeRequest, db: Session = Depends(get_db)):
    """
    Sell all shares of a symbol

    Args:
        trade: TradeRequest with strategy_name, symbol, and current price
        db: Database session

    Returns:
        TradeResponse with order details and updated portfolio state
    """
    try:
        # Get portfolio state
        portfolio = db.query(PortfolioState).filter(
            PortfolioState.strategy_name == trade.strategy_name
        ).first()

        if not portfolio:
            raise HTTPException(
                status_code=404,
                detail=f"Portfolio not found for strategy {trade.strategy_name}"
            )

        # Get position
        position = db.query(Position).filter(
            Position.strategy_name == trade.strategy_name,
            Position.symbol == trade.symbol
        ).first()

        if not position or position.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"No position found for {trade.symbol} in strategy {trade.strategy_name}"
            )

        shares_to_sell = position.quantity
        total_proceeds = shares_to_sell * trade.price

        # Determine trading mode and execute trade
        trading_mode = get_trading_mode()

        if trading_mode == "PAPER":
            # Paper trade - just log it
            trade_result = execute_paper_trade("SELL", trade.symbol, shares_to_sell, trade.price)
        else:  # LIVE
            # Live trade - call IBKR
            trade_result = execute_live_trade("SELL", trade.symbol, shares_to_sell, trade.price)

        # Create order record
        order = Order(
            strategy_name=trade.strategy_name,
            symbol=trade.symbol,
            order_type="SELL",
            quantity=shares_to_sell,
            price=trade.price,
            order_value=total_proceeds,
            status=trade_result["status"],
            trading_mode=trading_mode,
            ibkr_order_id=trade_result["ibkr_order_id"],
            execution_timestamp=trade_result["execution_timestamp"]
        )
        db.add(order)

        # Update portfolio state
        portfolio.cash += total_proceeds
        portfolio.total_value = portfolio.cash

        # Check if still invested in any positions (before deleting current position)
        remaining_positions = db.query(Position).filter(
            Position.strategy_name == trade.strategy_name,
            Position.id != position.id
        ).count()
        portfolio.invested = remaining_positions > 0
        portfolio.position_locked = remaining_positions > 0  # Unlock when all positions closed

        # Remove position
        db.delete(position)

        db.commit()
        db.refresh(order)

        logger.info(f"SELL_ALL executed: {trade.strategy_name} sold {shares_to_sell} {trade.symbol} @ ${trade.price:.2f}")

        return TradeResponse(
            order_id=order.id,
            strategy_name=trade.strategy_name,
            symbol=trade.symbol,
            order_type="SELL",
            quantity=shares_to_sell,
            price=trade.price,
            order_value=total_proceeds,
            allocated_capital=portfolio.allocated_capital,
            remaining_cash=portfolio.cash,
            invested=portfolio.invested
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in sell_all: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
