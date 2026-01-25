# MultiStrategy Portfolio API

A FastAPI-based microservice for managing multi-strategy portfolios with dynamic capital allocation.

## Overview

This API provides endpoints for:
- Managing orders across multiple strategies
- Tracking positions per strategy
- Dynamic capital allocation with rebalancing
- Support for both PAPER and LIVE trading modes

## Key Features

### Capital Allocation
- **Dynamic Rebalancing**: Allocate capital based on risk-adjusted performance (Sharpe ratio, returns, drawdown)
- **Position Locking**: Strategies with open positions maintain their allocation during rebalancing
- **Equal Weight or Risk-Adjusted**: Choose allocation method based on your needs

### Trade Execution
- **buy_all**: Each strategy buys using their `allocated_capital`, not total portfolio cash
- **sell_all**: Close positions and unlock strategy for rebalancing
- **PAPER/LIVE modes**: Seamlessly switch between paper trading and live execution

## Architecture

```
MultiStrategyAPI/
├── api/
│   ├── orders.py       # Order creation, buy_all, sell_all
│   ├── positions.py    # Position tracking
│   └── portfolio.py    # Portfolio state, allocation, rebalancing
├── schemas/
│   ├── order.py        # Order request/response models
│   ├── position.py     # Position request/response models
│   └── portfolio.py    # Portfolio state models
├── models.py           # SQLAlchemy database models
├── database.py         # Database configuration
├── allocation.py       # CapitalAllocator class
└── main.py            # FastAPI app
```

## API Endpoints

### Orders

#### POST `/orders`
Create a new order record.

**Request:**
```json
{
  "strategy_name": "strategy1",
  "symbol": "SPY",
  "order_type": "BUY",
  "quantity": 100,
  "price": 450.00
}
```

#### POST `/orders/buy_all`
Buy as many shares as possible using the strategy's allocated capital.

**Request:**
```json
{
  "strategy_name": "strategy1",
  "symbol": "SPY",
  "price": 450.00
}
```

**Response:**
```json
{
  "order_id": 1,
  "strategy_name": "strategy1",
  "symbol": "SPY",
  "order_type": "BUY",
  "quantity": 22,
  "price": 450.00,
  "order_value": 9900.00,
  "allocated_capital": 10000.00,
  "remaining_cash": 100.00,
  "invested": true
}
```

**Important:** `buy_all` uses `allocated_capital` to determine buying power, ensuring each strategy only trades within its allocation.

#### POST `/orders/sell_all`
Sell all shares of a symbol for a strategy.

**Request:**
```json
{
  "strategy_name": "strategy1",
  "symbol": "SPY",
  "price": 455.00
}
```

#### GET `/orders`
Get orders with optional filters.

**Query Parameters:**
- `strategy_name` (optional)
- `symbol` (optional)
- `status` (optional): PENDING, EXECUTED, FAILED
- `limit` (optional): default 100

#### PUT `/orders/{order_id}/status`
Update order status.

**Request:**
```json
{
  "status": "EXECUTED",
  "execution_price": 450.25
}
```

### Positions

#### GET `/positions`
Get all positions with optional filters.

**Query Parameters:**
- `strategy_name` (optional)
- `symbol` (optional)

#### POST `/positions`
Create or update a position.

**Request:**
```json
{
  "strategy_name": "strategy1",
  "symbol": "SPY",
  "quantity": 100,
  "avg_price": 450.00,
  "current_price": 455.00
}
```

#### DELETE `/positions/{position_id}`
Delete a position (when fully closed).

### Portfolio

#### POST `/portfolio/initialize`
Initialize portfolio states for multiple strategies.

**Request:**
```json
{
  "strategies": ["strategy1", "strategy2", "strategy3"],
  "total_capital": 100000,
  "allocation_method": "equal_weight"
}
```

**Response:**
```json
{
  "total_capital": 100000,
  "allocation_method": "equal_weight",
  "portfolios": [
    {
      "strategy_name": "strategy1",
      "allocated_capital": 33333.33,
      "cash": 33333.33
    },
    {
      "strategy_name": "strategy2",
      "allocated_capital": 33333.33,
      "cash": 33333.33
    },
    {
      "strategy_name": "strategy3",
      "allocated_capital": 33333.34,
      "cash": 33333.34
    }
  ]
}
```

#### POST `/portfolio/rebalance`
Trigger portfolio rebalancing based on performance.

**Request:**
```json
{
  "total_capital": 100000,
  "strategies": ["strategy1", "strategy2", "strategy3"],
  "allocation_method": "risk_adjusted"
}
```

**Response:**
```json
{
  "total_capital": 100000,
  "allocation_method": "risk_adjusted",
  "rebalance_timestamp": "2026-01-17T12:00:00",
  "allocation_details": {
    "strategy1": {
      "allocated": 45000,
      "previous": 33333.33,
      "change": 11666.67,
      "locked": false
    },
    "strategy2": {
      "allocated": 35000,
      "previous": 33333.33,
      "change": 1666.67,
      "locked": true
    },
    "strategy3": {
      "allocated": 20000,
      "previous": 33333.34,
      "change": -13333.34,
      "locked": false
    }
  }
}
```

**Note:** Strategies with `locked: true` (currently holding positions) maintain their allocation. Only unlocked strategies get rebalanced.

#### GET `/portfolio/allocation/current`
Get current capital allocation across all strategies.

**Response:**
```json
{
  "total_cash": 100000,
  "total_allocated": 100000,
  "total_locked": 35000,
  "allocations": {
    "strategy1": {
      "allocated": 45000,
      "cash": 45000,
      "locked": false,
      "invested": false,
      "total_value": 45000
    },
    "strategy2": {
      "allocated": 35000,
      "cash": 5000,
      "locked": true,
      "invested": true,
      "total_value": 35000
    }
  },
  "last_rebalance": "2026-01-17T12:00:00"
}
```

#### GET `/portfolio/allocation/history`
Get historical allocation changes.

**Query Parameters:**
- `limit` (optional): default 50

#### GET `/portfolio/{strategy_name}`
Get portfolio state for a specific strategy.

#### GET `/portfolio`
Get portfolio state for all strategies.

#### GET `/portfolio/{strategy_name}/invested`
Get invested status for a specific strategy.

## Database Models

### PortfolioState
- `strategy_name`: Strategy identifier (unique)
- `cash`: Current cash balance
- `allocated_capital`: Capital allocated to this strategy (used by buy_all)
- `initial_cash`: Starting capital
- `total_value`: Cash + position values
- `invested`: Whether strategy currently has positions
- `position_locked`: Prevents rebalancing when true

### Order
- `strategy_name`: Strategy that placed the order
- `symbol`: Trading symbol
- `order_type`: BUY or SELL
- `quantity`: Number of shares
- `price`: Execution price
- `status`: PENDING, EXECUTED, FAILED
- `trading_mode`: PAPER or LIVE

### Position
- `strategy_name`: Strategy holding the position
- `symbol`: Trading symbol
- `quantity`: Number of shares
- `avg_price`: Average purchase price
- `current_price`: Current market price
- `market_value`: quantity × current_price
- `unrealized_pnl`: (current_price - avg_price) × quantity

### AllocationHistory
- `timestamp`: When rebalancing occurred
- `total_capital`: Total capital at rebalance
- `allocations`: JSON with allocation details per strategy
- `rebalance_reason`: Why rebalancing was triggered

## Capital Allocation Strategy

The `CapitalAllocator` class implements two allocation methods:

### Equal Weight
Simple: divide capital equally across all strategies.

### Risk-Adjusted (Default)
Allocates capital based on:
1. **Sharpe Ratio**: Risk-adjusted returns
2. **Total Returns**: Recent performance
3. **Maximum Drawdown**: Risk management

**Score Formula:**
```
score = (1 + sharpe) × (1 + returns%) × (1 / (1 + drawdown%))
```

**Constraints:**
- Min allocation: 10% per strategy
- Max allocation: 50% per strategy
- Locked strategies: maintain current allocation

## Environment Variables

- `TRADING_MODE`: PAPER or LIVE (default: PAPER)
- `DATABASE_URL`: PostgreSQL connection string (default: postgresql://postgres:postgres@postgres:5432/multistrategy)

## Running the API

### Development
```bash
cd portfolio_multi_strategy/MultiStrategyAPI
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### With Docker
```bash
docker-compose up multistrategy-api
```

## API Documentation

Once running, access:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Example Workflow

1. **Initialize portfolios**
```bash
curl -X POST http://localhost:8000/portfolio/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "strategies": ["momentum", "mean_reversion", "breakout"],
    "total_capital": 100000,
    "allocation_method": "equal_weight"
  }'
```

2. **Strategy executes buy_all**
```bash
curl -X POST http://localhost:8000/orders/buy_all \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "momentum",
    "symbol": "SPY",
    "price": 450.00
  }'
```

3. **Check current allocation**
```bash
curl http://localhost:8000/portfolio/allocation/current
```

4. **Trigger rebalancing**
```bash
curl -X POST http://localhost:8000/portfolio/rebalance \
  -H "Content-Type: application/json" \
  -d '{
    "total_capital": 100000,
    "strategies": ["momentum", "mean_reversion", "breakout"],
    "allocation_method": "risk_adjusted"
  }'
```

5. **Strategy closes position**
```bash
curl -X POST http://localhost:8000/orders/sell_all \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "momentum",
    "symbol": "SPY",
    "price": 455.00
  }'
```

## Integration with Strategies

Strategies should:
1. Call `GET /portfolio/{strategy_name}/invested` to check if already invested
2. Call `POST /orders/buy_all` to enter positions
3. Call `POST /orders/sell_all` to exit positions
4. The API automatically manages `allocated_capital` and position locking

## Notes

- **Position Locking**: When a strategy calls `buy_all`, `position_locked` is set to `true`, preventing rebalancing until the position is closed
- **Allocated Capital**: Each strategy's `buy_all` uses their `allocated_capital`, not the total portfolio cash
- **Rebalancing**: Only affects unlocked strategies (those not holding positions)
- **Pydantic Config**: Uses `from_attributes = True` (Pydantic v2) instead of `orm_mode`
