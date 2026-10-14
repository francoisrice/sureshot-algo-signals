# SureshotSDK

Shared building blocks for Sureshot algorithmic trading strategies.

- **Strategy base class**: `TradingStrategy` (lifecycle, scheduling, signal handling, order helpers)
- **Indicators**: `SMA`, `EMA`, `ATR`, `BollingerBand`
- **Backtesting**: `BacktestEngine`, `BacktestRunner`, `Portfolio`
- **Market data**: `AlpacaDataClient`, `PolygonClient`, `HistoricalDataClient`, `MarketDataStore`
- **Brokers**: `TastytradeClient` (OAuth2), `IBKRClient` (Client Portal Gateway)

## Install

```bash
pip install SureshotSDK                 # core
pip install "SureshotSDK[ibkr]"         # + IBKR browser-automated login (Playwright)
pip install "SureshotSDK[options]"      # + Black-Scholes pricing (SciPy)
pip install "SureshotSDK[all]"          # everything
```

Python 3.10+.

## Quick examples

Real-time price from Alpaca:

```python
from SureshotSDK import AlpacaDataClient

data = AlpacaDataClient()          # reads ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY
print(data.get_current_price("GLDM"))
bars = data.get_historical_data("GLDM", start_date, end_date, "1d")   # [{t, o, h, l, c, v}, ...]
```

Market order on tastytrade, confirmed:

```python
from SureshotSDK import TastytradeClient

broker = TastytradeClient(environment="SANDBOX")   # or "LIVE"
response = broker.buy("GLDM", 10)
order = broker.wait_for_fill(response["data"]["order"]["id"])
print(order["status"], TastytradeClient.average_fill_price(order))
```

`TastytradeClient` environment variables (suffix `_LIVE` or `_SANDBOX`):
`ACCT_NUMBER_*`, `TT_CLIENT_SECRET_*`, `TT_REFRESH_TOKEN_*`.

## Disclaimer

Trading involves substantial risk of loss. This software is provided as-is, with no warranty,
and is not investment advice.
