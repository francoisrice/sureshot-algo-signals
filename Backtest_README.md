# How to Backtest

1, Start the PortfolioAPI

Example:
```bash
uvicorn portfolio_multi_strategy.MultiStrategyAPI.main:app --reload --host 0.0.0.0 --port 8000
```

Then modify and run the backtest script
```bash
python backtest.py
```

# Create Portfolios and strategies to add to the portfolio

Create a strategy and import the SureshotSDK.TradingStrategy

...