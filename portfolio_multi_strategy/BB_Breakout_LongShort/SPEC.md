# Bollinger Band Breakout Long/Short

Strategy Name: Sidearm

## Core Strategy Metrics

15min bars

Long Entry: Price >= BollingerBand(length=20,stddev=2.0) and Price >= EMA(80) and EMA(80) >= EMA(200)
Take Profit Long: 20%
Stop Loss Long: 3%

Short Entry: Price <= BollingerBand(length=20,stddev=2.0) and Price <= EMA(80) and EMA(80) <= EMA(200)
Take Profit Short: 20%
Stop Loss Short: 3%

## Optimizable Attributes

FastEMA
SlowEMA
BollingerBandLength
BollingerBandStdDev
Take Profit Long
Stop Loss Long
Take Profit Short
Stop Loss Short

## Variants

- 

## During backtesting

### Handled in main.py

- Process on_minute bars for entries and exits

### Handled in TradingStrategy.py or SureshotSDK

- Pull fast and slow EMA, `self.fastEMA = SureshotSDK.EMA(self.signalSymbol, FAST_EMA_PERIOD, self.timeframe)`
- Pull Bollinger Band, `self.BB = SureshotSDK.BollingerBand(self.signalSymbol, BB_PERIOD, BB_STD_DEV, self.timeframe)`

## During live trading

- Pull a live price for entries and real-time pricing from data-fetcher.
- Execute orders via IBKR.

## During paper trading

- Pull real data with the same method used for live trading
- Monitor prices and track returns without sending to IBKR
