# short iron butterfly spec

Strategy Name: Plasma Blade

## Core Strategy Metrics

Sell Put 1 strike above the money
Sell Call 1 strike below the money
    If Price is within $0.20 of the strike price, sell the call and put at that strike price

Buy Put 10 strikes OTM
Buy Call 10 strikes OTM

Close at 10% of total profit
Let it ride if it's a loser

## Optimizable Attributes

(Maybe take-profit, but 10% might be the best across regimes)

## Variants

- Select wings 10 strikes out vs strikes 20Del or lower
- Select wings 10 strikes out vs 20Del, 15Del, 10Del, 5Del
- Start trading at 9:30am, all day vs 10am, all day vs 9:30a, 1 trade vs 10am, 1 trade
- Profit target: 10% -> 100%
- VIX-gating: Only trade when VIX is below 25 or 30 or 40...
- Stop-loss? 50% -> 200% of credit

- v1: 1 trade per day in the morning
- (v2: continuous trading, taking profit at defined level)

## During backtesting

### Handled in main.py

- query the option price of a call. References a TradingStrategy.py function.
- query the option price of a put. References a TradingStrategy.py function.
- Process on_minute bars to calculate when to get out

### Handled in TradingStrategy.py or SureshotSDK

- strategy will use historical price data to pull prices for the trading symbol
- Use BlackScholes.py in SureshotSDK.options to calculate the options price during the backtest date
- Use the options price to calculate the premium received for the options sold
- Use the options price to calculate the premium paid for the options bought
- The Strategy should check the simulated price of the option with each on_minute. In TradingStrategy.py or another object, run BlackScholes.py and return the simulated price given the underlying price data
    - BlackScholes.py should use cached and in-memory pricing data
    - The strategy should hold state for the % of profit and price the simulated options need to hit before exiting, the same way that ORB_Aziz holds its stop-loss in state.

## During live trading

- Pull a live option chain for entries and real-time pricing. BrowserBase price_fetcher will need new methods to fetch this data. Nasdaq.com has option chains, but the data may require pagination.
- Execute options order via IBKR options trades.

## During paper trading

- Pull real options data with the same method used for live trading
- Monitor prices and track returns without sending to IBKR
