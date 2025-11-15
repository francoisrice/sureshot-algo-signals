"""
Indicator API router
Endpoints for recording and retrieving technical indicators
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ..database import get_db
from ..models import Indicator
from ..schemas import IndicatorCreate, IndicatorResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.post("", response_model=IndicatorResponse, status_code=201)
async def create_indicator(indicator: IndicatorCreate, db: Session = Depends(get_db)):
    """Record a technical indicator value"""
    try:
        db_indicator = Indicator(
            strategy_name=indicator.strategy_name,
            symbol=indicator.symbol,
            indicator_type=indicator.indicator_type,
            period=indicator.period,
            timeframe=indicator.timeframe,
            value=indicator.value
        )

        db.add(db_indicator)
        db.commit()
        db.refresh(db_indicator)

        logger.info(f"Indicator created: {indicator.strategy_name} {indicator.indicator_type} {indicator.symbol} = {indicator.value}")

        return db_indicator
    except Exception as e:
        logger.error(f"Error creating indicator: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/latest", response_model=List[IndicatorResponse])
async def get_latest_indicators(
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    indicator_type: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get the latest indicator values with optional filters"""
    query = db.query(Indicator)

    if strategy_name:
        query = query.filter(Indicator.strategy_name == strategy_name)
    if symbol:
        query = query.filter(Indicator.symbol == symbol)
    if indicator_type:
        query = query.filter(Indicator.indicator_type == indicator_type)

    indicators = query.order_by(Indicator.timestamp.desc()).limit(limit).all()
    return indicators


@router.get("/{indicator_id}", response_model=IndicatorResponse)
async def get_indicator(indicator_id: int, db: Session = Depends(get_db)):
    """Get indicator by ID"""
    db_indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not db_indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return db_indicator
