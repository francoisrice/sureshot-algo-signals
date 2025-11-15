"""
Position API router
Endpoints for managing portfolio positions
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ..database import get_db
from ..models import Position
from ..schemas import PositionUpdate, PositionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/positions", tags=["positions"])


@router.post("", response_model=PositionResponse)
async def upsert_position(position: PositionUpdate, db: Session = Depends(get_db)):
    """Create or update a position"""
    try:
        # Check if position exists
        db_position = db.query(Position).filter(
            Position.strategy_name == position.strategy_name,
            Position.symbol == position.symbol
        ).first()

        if db_position:
            # Update existing position
            db_position.quantity = position.quantity
            db_position.avg_price = position.avg_price
            if position.current_price:
                db_position.current_price = position.current_price
                db_position.market_value = position.quantity * position.current_price
                db_position.unrealized_pnl = (position.current_price - position.avg_price) * position.quantity
        else:
            # Create new position
            market_value = None
            unrealized_pnl = None
            if position.current_price:
                market_value = position.quantity * position.current_price
                unrealized_pnl = (position.current_price - position.avg_price) * position.quantity

            db_position = Position(
                strategy_name=position.strategy_name,
                symbol=position.symbol,
                quantity=position.quantity,
                avg_price=position.avg_price,
                current_price=position.current_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl
            )
            db.add(db_position)

        db.commit()
        db.refresh(db_position)

        logger.info(f"Position updated: {position.strategy_name} {position.symbol} {position.quantity} shares")

        return db_position
    except Exception as e:
        logger.error(f"Error upserting position: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{position_id}")
async def delete_position(position_id: int, db: Session = Depends(get_db)):
    """Delete a position (when fully closed)"""
    db_position = db.query(Position).filter(Position.id == position_id).first()
    if not db_position:
        raise HTTPException(status_code=404, detail="Position not found")

    db.delete(db_position)
    db.commit()

    logger.info(f"Position {position_id} deleted")

    return {"message": "Position deleted"}


@router.get("", response_model=List[PositionResponse])
async def get_positions(
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all positions with optional filters"""
    query = db.query(Position)

    if strategy_name:
        query = query.filter(Position.strategy_name == strategy_name)
    if symbol:
        query = query.filter(Position.symbol == symbol)

    positions = query.all()
    return positions


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(position_id: int, db: Session = Depends(get_db)):
    """Get position by ID"""
    db_position = db.query(Position).filter(Position.id == position_id).first()
    if not db_position:
        raise HTTPException(status_code=404, detail="Position not found")
    return db_position
