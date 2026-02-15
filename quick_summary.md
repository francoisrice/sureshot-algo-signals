
Follow-up
**How can we handle boundary conditions for SMA, ATR, etc...**
    -> User sets boundary conditions for values that need warmup, until we have more data...
    -> Warmup is the best practice for this
        -> With current data constraints, only doesn't work for multi-year strategies
**Add dates to Order for backtests**
**Need to create a real README for starting the PortfolioAPI and backtests, & how users should create TradingStrategies**
**In PortfolioAPI, after buy_all or sell_all, portfolio logic should rebalance allocations based on strategy performance and forecasts**
2. Need to use the same logger/loglevel