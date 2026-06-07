"""
MultiStrategy Portfolio API - Main Application
Microservice for managing multi-strategy portfolios with dynamic capital allocation
"""

import os
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .database import init_db, SessionLocal
from .models import PortfolioState, AllocationHistory, StrategyConfig
from .allocation import CapitalAllocator
from .api import orders, positions, portfolio, config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="MultiStrategy Portfolio API",
    description="Portfolio management with dynamic capital allocation across multiple strategies",
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
app.include_router(config.router)


def _auto_initialize_portfolios():
    """Seed PortfolioState rows on first startup. Skips if rows already exist."""
    trading_mode = os.getenv("TRADING_MODE", "PAPER")
    strategies_env = os.getenv("PORTFOLIO_STRATEGIES", "")

    if not strategies_env:
        logger.warning(
            "PORTFOLIO_STRATEGIES not set — skipping auto-init. "
            "Call POST /portfolio/initialize manually."
        )
        return

    strategies = [s.strip() for s in strategies_env.split(",") if s.strip()]

    if trading_mode == "LIVE":
        from SureshotSDK.ibkr.automation.client import IBKRClient
        logger.info("LIVE mode — fetching account balance from IBKR for capital initialization...")
        ibkr = IBKRClient()
        total_capital = ibkr.fetch_acct_balance()
        if total_capital is None:
            logger.error(
                "fetch_acct_balance() returned None — cannot auto-initialize portfolios. "
                "Check IBKR gateway connectivity, then call POST /portfolio/initialize manually."
            )
            return
        logger.info(f"IBKR net liquidation value: ${total_capital:,.2f}")
    else:
        total_capital_env = os.getenv("PORTFOLIO_TOTAL_CAPITAL", "")
        if not total_capital_env:
            logger.warning(
                "PORTFOLIO_TOTAL_CAPITAL not set — skipping auto-init. "
                "Call POST /portfolio/initialize manually."
            )
            return
        total_capital = float(total_capital_env)
        logger.info(f"PAPER mode — using configured capital: ${total_capital:,.2f}")

    db = SessionLocal()
    try:
        existing = {
            p.strategy_name
            for p in db.query(PortfolioState.strategy_name).all()
        }
        new_strategies = [s for s in strategies if s not in existing]

        if not new_strategies:
            logger.info(f"All {len(strategies)} strategies already initialized — skipping")
            return

        per_strategy = total_capital / len(new_strategies)
        for strategy_name in new_strategies:
            db.add(PortfolioState(
                strategy_name=strategy_name,
                cash=per_strategy,
                allocated_capital=per_strategy,
                initial_cash=per_strategy,
                total_value=per_strategy,
                invested=False,
                position_locked=False,
                total_return=0.0,
                total_return_pct=0.0,
            ))

        db.add(AllocationHistory(
            timestamp=datetime.utcnow(),
            total_capital=total_capital,
            allocations={s: {"allocated": per_strategy, "locked": False} for s in new_strategies},
            rebalance_reason="Auto-initialized on startup",
        ))
        db.commit()
        logger.info(
            f"Auto-initialized {len(new_strategies)} portfolios "
            f"(${per_strategy:,.2f} each, ${total_capital:,.2f} total)"
        )

    except Exception as e:
        logger.error(f"Portfolio auto-initialization failed: {e}")
        db.rollback()
    finally:
        db.close()


def _seed_strategy_configs(strategies: list) -> None:
    """
    Create a PAPER StrategyConfig row for any strategy that doesn't have one yet.
    Never overwrites existing rows — the DB is the sole source of truth for
    LIVE/PAPER assignment after initial seeding.
    """
    db = SessionLocal()
    try:
        for strategy_name in strategies:
            exists = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy_name
            ).first()
            if not exists:
                db.add(StrategyConfig(strategy_name=strategy_name, trading_mode="PAPER"))
                logger.info(f"Seeded StrategyConfig: {strategy_name} -> PAPER (default)")
        db.commit()
    except Exception as e:
        logger.error(f"Failed to seed strategy configs: {e}")
        db.rollback()
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    logger.info("Starting MultiStrategy Portfolio API...")
    trading_mode = os.getenv("TRADING_MODE", "PAPER")
    logger.info(f"Trading mode: {trading_mode}")
    init_db()
    logger.info("Database initialized")
    _auto_initialize_portfolios()
    strategies_env = os.getenv("PORTFOLIO_STRATEGIES", "")
    if strategies_env:
        strategies = [s.strip() for s in strategies_env.split(",") if s.strip()]
        _seed_strategy_configs(strategies)


@app.get("/")
async def root():
    """Health check endpoint"""
    trading_mode = os.getenv("TRADING_MODE", "PAPER")
    return {
        "service": "MultiStrategy Portfolio API",
        "status": "healthy",
        "version": "1.0.0",
        "trading_mode": trading_mode,
        "features": [
            "Multi-strategy portfolio management",
            "Dynamic capital allocation",
            "Risk-adjusted rebalancing",
            "Position locking during trades"
        ]
    }


@app.get("/health")
async def health_check():
    """Kubernetes health check"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
