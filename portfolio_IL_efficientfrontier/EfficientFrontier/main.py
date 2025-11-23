"""
EfficientFrontier API - Main Application
Microservice for processing buy/sell orders from IL strategies and managing portfolio state
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .database import init_db
from .api import orders, positions, portfolio, indicators

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="EfficientFrontier API",
    description="Order processing and portfolio management for Incredible Leverage strategies",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(portfolio.router)
app.include_router(indicators.router)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    logger.info("Starting EfficientFrontier API...")
    trading_mode = os.getenv("TRADING_MODE", "PAPER")
    logger.info(f"Trading mode: {trading_mode}")
    init_db()
    logger.info("Database initialized")


@app.get("/")
async def root():
    """Health check endpoint"""
    trading_mode = os.getenv("TRADING_MODE", "PAPER")
    return {
        "service": "EfficientFrontier API",
        "status": "healthy",
        "version": "1.0.0",
        "trading_mode": trading_mode
    }


@app.get("/health")
async def health_check():
    """Kubernetes health check"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
