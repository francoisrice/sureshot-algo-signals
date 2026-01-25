# Multi-Strategy Portfolio

A multi-strategy trading portfolio combining three distinct trading strategies with dynamic capital allocation.

## Strategies

### 1. Incredible Leverage (SPXL)
- **Type**: Monthly momentum
- **Symbol**: SPXL (3x leveraged S&P 500)
- **Entry**: Month-end when SPY > 252-day SMA
- **Exit**: Month-end when SPY < SMA OR 5% stop-loss
- **Rebalance**: Immediate when out of position

### 2. Opening Range Breakout (ORB)
- **Type**: Intraday breakout
- **Symbol**: Daily scan for highest volume stock with >10% ATR
- **Entry**: Breakout of 5-minute opening range
- **Exit**: Take-profit (30% ATR) OR stop-loss (50% ATR) OR EOD
- **Rebalance**: Every 60 days when out of position

### 3. Naked Wheel (SPY)
- **Type**: Options income
- **Symbol**: SPY options
- **Entry**: Sell OTM puts/calls at 1.6% OTM, 10+ DTE
- **Exit**: Take-profit (30% gain) OR assignment
- **Rebalance**: Every 180 days when out of position

## Architecture

```
portfolio_multi_strategy/
├── MultiStrategyAPI/          # Portfolio management service
│   ├── main.py               # FastAPI application
│   ├── allocation.py         # Dynamic capital allocation logic
│   ├── api/                  # API endpoints
│   ├── schemas/              # Pydantic models
│   └── models.py             # Database models
├── IncredibleLeverage_SPXL/  # Strategy 1
│   └── main.py
├── ORB_SPY/                  # Strategy 2
│   ├── main.py
│   └── scanner.py
├── NakedWheel_SPY/           # Strategy 3
│   └── main.py
├── deployment.yaml           # Kubernetes deployment
└── README.md                 # This file
```

## Running Modes

Each strategy can run in three modes by setting the `TRADING_MODE` environment variable:

### LIVE Mode
```bash
export TRADING_MODE=LIVE
export API_URL=http://localhost:8000
python portfolio_multi_strategy/IncredibleLeverage_SPXL/main.py
```

### BACKTEST Mode
```bash
# Edit backtest.py configuration
python backtest.py
```

### OPTIMIZATION Mode
```bash
export TRADING_MODE=OPTIMIZATION
# Optimization framework calls strategy methods directly
```

## Backtesting

Run backtests using the root-level `backtest.py`:

```python
# Edit these values in backtest.py
PORTFOLIO = "portfolio_multi_strategy"
STRATEGY = "IncredibleLeverage_SPXL"  # or ORB_SPY, NakedWheel_SPY
START_DATE = datetime(2020, 1, 1)
END_DATE = datetime(2024, 12, 31)
INITIAL_CASH = 100000
```

Then run:
```bash
python backtest.py
```

## Deployment

### Local Development

1. Start the portfolio API:
```bash
cd portfolio_multi_strategy/MultiStrategyAPI
uvicorn main:app --reload
```

2. Start each strategy in separate terminals:
```bash
export TRADING_MODE=LIVE
export API_URL=http://localhost:8000

# Terminal 1
python portfolio_multi_strategy/IncredibleLeverage_SPXL/main.py

# Terminal 2
python portfolio_multi_strategy/ORB_SPY/main.py

# Terminal 3
python portfolio_multi_strategy/NakedWheel_SPY/main.py
```

### Kubernetes Deployment

1. Create secrets:
```bash
kubectl create secret generic trading-secrets \
  --from-literal=polygon-api-key=YOUR_KEY \
  --from-literal=ibkr-username=YOUR_USERNAME \
  --from-literal=ibkr-password=YOUR_PASSWORD
```

2. Deploy:
```bash
kubectl apply -f portfolio_multi_strategy/deployment.yaml
```

3. Check status:
```bash
kubectl get pods -l app=multistrategy
kubectl logs -f deployment/multistrategy-portfolio -c multistrategy-api
```

## Capital Allocation

The portfolio uses dynamic capital allocation based on risk-adjusted performance:

- **Score Calculation**: (1 + Sharpe) × (1 + Returns) / (1 + Drawdown)
- **Rebalancing**: Only rebalances unlocked strategies (those not in positions)
- **Constraints**: Min 10%, Max 50% allocation per strategy

### Allocation API Endpoints

- `POST /portfolio/initialize` - Initialize strategy allocations
- `POST /portfolio/rebalance` - Trigger rebalancing
- `GET /portfolio/allocation/current` - View current allocations
- `GET /portfolio/allocation/history` - View allocation history

## Trading API Endpoints

### Orders
- `POST /orders/buy_all` - Buy using allocated capital
- `POST /orders/sell_all` - Sell and unlock position
- `GET /orders` - List all orders

### Positions
- `GET /positions` - List all positions
- `GET /positions/{strategy_name}` - Get positions for strategy

### Portfolio
- `GET /portfolio/{strategy_name}` - Get portfolio state

## Environment Variables

- `TRADING_MODE`: LIVE, BACKTEST, or OPTIMIZATION
- `API_URL`: Portfolio API URL (default: http://localhost:8000)
- `DATABASE_URL`: PostgreSQL connection string
- `POLYGON_API_KEY`: Polygon.io API key
- `IBKR_USERNAME`: Interactive Brokers username
- `IBKR_PASSWORD`: Interactive Brokers password

## Testing

Each strategy can be tested independently:

```bash
# Test Incredible Leverage
export TRADING_MODE=BACKTEST
python -c "from portfolio_multi_strategy.IncredibleLeverage_SPXL.main import IncredibleLeverageSPXL; s = IncredibleLeverageSPXL(); s.backtest_initialize(); print('OK')"

# Test ORB
python -c "from portfolio_multi_strategy.ORB_SPY.main import ORBStrategy; s = ORBStrategy(); s.backtest_initialize(); print('OK')"

# Test Naked Wheel
python -c "from portfolio_multi_strategy.NakedWheel_SPY.main import NakedWheelSPY; s = NakedWheelSPY(); s.backtest_initialize(); print('OK')"
```

## Notes

- ORB requires minute bar data - only works with paid Polygon.io tier
- Naked Wheel uses Black-Scholes simulation in backtest mode
- All strategies automatically switch between LIVE/BACKTEST/OPTIMIZATION modes
- Position locks prevent capital reallocation during active trades
