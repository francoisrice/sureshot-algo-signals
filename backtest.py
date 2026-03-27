"""
Unified Backtest Runner

Run backtests for any strategy in any portfolio by editing the configuration below.

Usage:
    1. Edit the configuration variables below
    2. Run: python backtest.py

The strategy will be dynamically imported and run in backtest mode.
"""

import os
import sys
import signal
import asyncio
import logging
from datetime import datetime
import importlib

# Import backtesting framework
from SureshotSDK import BacktestRunner

# ============================================================================
# BACKTEST CONFIGURATION - EDIT THESE VALUES
# ============================================================================

# Portfolio and strategy selection
PORTFOLIO = "portfolio_multi_strategy"
# STRATEGY = "IncredibleLeverage_SPXL"  # Options: IncredibleLeverage_SPXL, ORB_SPY, NakedWheel_SPY
STRATEGY = "ORB_HighVolume"  # Options: IncredibleLeverage_SPXL, ORB_SPY, NakedWheel_SPY

# Backtest date range
# START_DATE = datetime(2023, 6, 1)
# START_DATE = datetime(2025, 12, 1)
# END_DATE = datetime(2025, 12, 31)

START_DATE = datetime(2025, 5, 1)
END_DATE = datetime(2025, 9, 30)

# Initial capital
INITIAL_CASH = 100000

# Cache settings
USE_CACHE = True
CACHE_DIR = ".backtest_cache"

# Logging level
LOG_LEVEL = logging.INFO

# ============================================================================
# BACKTEST RUNNER
# ============================================================================

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def run_backtest():
    """
    Dynamically import and run the specified strategy in backtest mode
    """
    logger.info("=" * 80)
    logger.info("BACKTEST RUNNER")
    logger.info("=" * 80)
    logger.info(f"Portfolio: {PORTFOLIO}")
    logger.info(f"Strategy: {STRATEGY}")
    logger.info(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    logger.info(f"Initial Cash: ${INITIAL_CASH:,.0f}")
    logger.info("=" * 80)

    # Set environment to BACKTEST mode
    os.environ["TRADING_MODE"] = "BACKTEST"

    # Build module path
    module_path = f"{PORTFOLIO}.{STRATEGY}.main"

    logger.info(f"\nImporting strategy module: {module_path}")

    try:
        # Dynamically import the strategy module
        strategy_module = importlib.import_module(module_path)

        # Get the strategy class
        # Convention: Strategy class name is the strategy folder name without underscores
        # e.g., IncredibleLeverage_SPXL -> IncredibleLeverageSPXL
        class_name = STRATEGY.replace("_", "")

        # Try to find the strategy class
        strategy_class = None
        for attr_name in dir(strategy_module):
            attr = getattr(strategy_module, attr_name)
            if (isinstance(attr, type) and
                attr_name.lower() == class_name.lower() and
                hasattr(attr, 'backtest_initialize')):
                strategy_class = attr
                break

        if strategy_class is None:
            # Fallback: try common patterns
            possible_names = [
                class_name,
                STRATEGY,
                f"{STRATEGY}Strategy",
                class_name + "Strategy"
            ]

            for name in possible_names:
                if hasattr(strategy_module, name):
                    strategy_class = getattr(strategy_module, name)
                    break

        if strategy_class is None:
            logger.error(f"Could not find strategy class in {module_path}")
            logger.error(f"Tried: {', '.join(possible_names)}")
            logger.error(f"Available classes: {[name for name in dir(strategy_module) if not name.startswith('_')]}")
            return None

        logger.info(f"Found strategy class: {strategy_class.__name__}")

        # Instantiate the strategy
        strategy = strategy_class()

        logger.info(f"Strategy instantiated: {strategy.name}")

        # Create backtest runner (this sets strategy.portfolio)
        logger.info("Creating backtest runner...")
        runner = BacktestRunner(
            strategy=strategy,
            start_date=START_DATE,
            end_date=END_DATE,
            initial_cash=INITIAL_CASH,
            use_cache=USE_CACHE,
            cache_dir=CACHE_DIR
        )

        # Initialize for backtesting (now that portfolio is set)
        logger.info("Initializing strategy for backtest mode...")
        strategy.backtest_initialize(START_DATE,END_DATE)

        # Run backtest
        logger.info("\nStarting backtest execution...")
        logger.info("This may take several minutes on the first run...")
        logger.info("Subsequent runs will be faster due to caching.\n")

        results = runner.run()

        # Display results
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST RESULTS")
        logger.info("=" * 80)

        if results:
            logger.info(f"Strategy: {strategy.name}")
            logger.info(f"Period: {START_DATE.date()} to {END_DATE.date()}")
            logger.info(f"Initial Capital: ${INITIAL_CASH:,.0f}")

            if hasattr(results, 'final_value'):
                logger.info(f"Final Value: ${results.final_value:,.2f}")
                total_return = results.final_value - INITIAL_CASH
                total_return_pct = (total_return / INITIAL_CASH) * 100
                logger.info(f"Total Return: ${total_return:,.2f} ({total_return_pct:.2f}%)")

            if hasattr(results, 'trades'):
                logger.info(f"Total Trades: {len(results.trades)}")

            logger.info("=" * 80)

            return results
        else:
            logger.error("Backtest returned no results")
            return None

    except ImportError as e:
        logger.error(f"Failed to import strategy module: {e}")
        logger.error(f"Make sure {PORTFOLIO}/{STRATEGY}/main.py exists")
        return None
    except Exception as e:
        logger.error(f"Error running backtest: {e}", exc_info=True)
        return None

async def main():
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
 
        print("\n")
        print("╔" + "═" * 78 + "╗")
        print("║" + " " * 25 + "BACKTEST RUNNER" + " " * 38 + "║")
        print("╚" + "═" * 78 + "╝")
        print("\n")

        results = await run_backtest()

        if results:
            print("\n✓ Backtest completed successfully!\n")
            sys.exit(0)
        else:
            print("\n✗ Backtest failed. Check logs for details.\n")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        # Run the async main function
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nGracefully shutting down...")
        sys.exit(0)

    # print("\n")
    # print("╔" + "═" * 78 + "╗")
    # print("║" + " " * 25 + "BACKTEST RUNNER" + " " * 38 + "║")
    # print("╚" + "═" * 78 + "╝")
    # print("\n")

    # results = run_backtest()

    # if results:
    #     print("\n✓ Backtest completed successfully!\n")
    #     sys.exit(0)
    # else:
    #     print("\n✗ Backtest failed. Check logs for details.\n")
    #     sys.exit(1)
