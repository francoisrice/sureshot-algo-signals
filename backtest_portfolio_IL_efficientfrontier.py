"""
Backtest Portfolio: Incredible Leverage Efficient Frontier

This script backtests the entire portfolio_IL_efficientfrontier portfolio,
which consists of 5 IncredibleLeverage strategies:
- SPXL (S&P 500 3x)
- PTIR (Palantir-based leveraged strategy)
- NVDL (NVIDIA 2x)
- HOOD (Robinhood)
- AVL (Broadcom leveraged strategy)

The backtest uses:
- Shared capital pool across all strategies
- Efficient frontier optimization for capital allocation
- 252-day SMA indicator with 5% mid-month stop loss
- Month-end entry/exit logic
"""

# Load environment variables from .env file BEFORE importing SureshotSDK
from dotenv import load_dotenv
load_dotenv()

import logging
from datetime import datetime
from SureshotSDK import PortfolioBacktestEngine, StrategyConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """
    Run backtest for the Incredible Leverage Efficient Frontier portfolio
    """
    logger.info("=" * 80)
    logger.info("PORTFOLIO BACKTEST: Incredible Leverage Efficient Frontier")
    logger.info("=" * 80)

    # Portfolio configuration
    PORTFOLIO_NAME = "portfolio_IL_efficientfrontier"
    INITIAL_CASH = 100000  # $100,000 starting capital
    SMA_PERIOD = 252  # 252-day (1 year) SMA
    MAX_MID_MONTH_LOSS = 0.05  # 5% stop loss

    # Backtest period
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2024, 12, 31)

    # Define the 5 strategies in the portfolio
    strategies = [
        StrategyConfig(
            name="IncredibleLeverage_SPXL",
            trading_symbol="SPXL",      # Direxion Daily S&P 500 Bull 3X ETF
            indicator_symbol="SPY",      # S&P 500 ETF (for SMA)
            sma_period=SMA_PERIOD,
            max_mid_month_loss=MAX_MID_MONTH_LOSS
        ),
        StrategyConfig(
            name="IncredibleLeverage_PTIR",
            trading_symbol="PTIR",       # Palantir leveraged strategy
            indicator_symbol="PLTR",     # Palantir stock (for SMA)
            sma_period=SMA_PERIOD,
            max_mid_month_loss=MAX_MID_MONTH_LOSS
        ),
        StrategyConfig(
            name="IncredibleLeverage_NVDL",
            trading_symbol="NVDL",       # GraniteShares 2x Long NVDA ETF
            indicator_symbol="NVDA",     # NVIDIA stock (for SMA)
            sma_period=SMA_PERIOD,
            max_mid_month_loss=MAX_MID_MONTH_LOSS
        ),
        StrategyConfig(
            name="IncredibleLeverage_HOOD",
            trading_symbol="HOOD",       # Robinhood stock
            indicator_symbol="HOOD",     # Use same symbol for SMA
            sma_period=SMA_PERIOD,
            max_mid_month_loss=MAX_MID_MONTH_LOSS
        ),
        StrategyConfig(
            name="IncredibleLeverage_AVL",
            trading_symbol="AVL",        # Broadcom leveraged strategy
            indicator_symbol="AVGO",      # Use same symbol for SMA
            sma_period=SMA_PERIOD,
            max_mid_month_loss=MAX_MID_MONTH_LOSS
        ),
    ]

    logger.info(f"\nPortfolio: {PORTFOLIO_NAME}")
    logger.info(f"Number of Strategies: {len(strategies)}")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Initial Capital: ${INITIAL_CASH:,.2f}")
    logger.info(f"\nStrategies:")
    for strategy in strategies:
        logger.info(f"  - {strategy.name}: {strategy.trading_symbol} (indicator: {strategy.indicator_symbol})")

    # Initialize portfolio backtest engine
    engine = PortfolioBacktestEngine(
        portfolio_name=PORTFOLIO_NAME,
        strategies=strategies,
        initial_cash=INITIAL_CASH,
        use_cache=True  # Cache price data to speed up subsequent runs
    )

    # Run backtest with efficient frontier optimization
    logger.info("\n" + "=" * 80)
    logger.info("STARTING BACKTEST")
    logger.info("=" * 80 + "\n")

    results = engine.run(
        start_date=start_date,
        end_date=end_date,
        optimization_method='efficient_frontier'  # Use efficient frontier for capital allocation
    )

    if results:
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info(f"\nFinal Portfolio Value: ${results['final_value']:,.2f}")
        logger.info(f"Total Return: {results['total_return_pct']:.2f}%")
        logger.info(f"CAGR: {results['cagr']:.2f}%")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.3f}")
        logger.info(f"Sortino Ratio: {results['sortino_ratio']:.3f}")
        logger.info(f"Max Drawdown: {results['max_drawdown']:.2f}%")
        logger.info(f"Total Trades: {results['total_trades']}")
        logger.info(f"Win Rate: {results['win_rate']:.2f}%")
    else:
        logger.error("\n" + "=" * 80)
        logger.error("BACKTEST FAILED")
        logger.error("=" * 80)

    logger.info("\nResults saved to backtest_results/ folder.")


if __name__ == "__main__":
    main()
