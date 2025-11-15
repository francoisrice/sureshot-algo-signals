"""
Order API router
Endpoints for creating and managing order records
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ..database import get_db
from ..models import Order
from ..schemas import OrderCreate, OrderStatusUpdate, OrderResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


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
            metadata=order.metadata,
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
        from datetime import datetime
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
