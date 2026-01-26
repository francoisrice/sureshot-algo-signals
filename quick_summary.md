
Follow-up
**How can we handle boundary conditions for SMA, ATR, etc...**
**Add dates to Order for backtests**
**Need to create a real README for starting the PortfolioAPI and backtests, & how users should create TradingStrategies**
**In PortfolioAPI, after buy_all or sell_all, portfolio logic should rebalance allocations based on strategy performance and forecasts**
3. Rework how backtest cache is used. Right now, it's a direct string match to the name of the JSON. It needs to match on timeframe (1d) and use the JSON file as long as it contains the correct data, even if it's a subset. If more data is needed, it should query it and concatenate it with the previous data.
2. Need to use the same logger/loglevel