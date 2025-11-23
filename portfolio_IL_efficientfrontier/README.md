# EfficientFrontier Portfolio

## Architecture

- This deployment creates multiple trading strategies that are managed through the EfficientFrontier Portfolio strategy.
- Each strategy stays idle, only checking price data at regular intervals set on initialization.
- At each interval, new price data is evaluated for a buy/sell order based on the strategy's logic.
- Each strategy is based on a Scheduler object that accesses to the Portfolio router via HTTP
- The buy/sell order is sent through the Portfolio to execute a paper trade or live order based on the Portfolio's logic
- The Portfolio API logic determines cash allocated to each strategy, manages positions, and decides which strategies to trade Live.
- All orders are Market orders

## Components

The deployment consists of 7 containers:

**1 EfficientFrontier Portfolio Router Container:**

- translates orders from each strategy to the database or brokerages
- manages cash allocation, position tracking, and order history
- FastAPI microservice on port 8000
- persists data in PostgreSQL database

**5 Strategy Containers:**

Leveraged Trading Strategies: SPXL, PTIR, NVDL, HOOD, AVL

**1 PostgreSQL Database Container:**

- Persistent storage for all strategy data
- Port 5432 (internal cluster access only)

## API Endpoints

**Trading Operations:**

- `POST /orders/buy_all` - Buy as many shares as possible with available cash
- `POST /orders/sell_all` - Sell all shares of a symbol
- `GET /portfolio/{strategy_name}/invested` - Check if strategy is currently invested

**Orders:**

- `POST /orders` - Create a new order
- `GET /orders` - List orders (filterable by strategy, symbol, status)
- `GET /orders/{order_id}` - Get specific order
- `PUT /orders/{order_id}/status` - Update order status

**Positions:**

- `POST /positions` - Create/update position
- `GET /positions` - List positions (filterable by strategy/symbol)
- `DELETE /positions/{position_id}` - Delete position

**Portfolio:**

- `POST /portfolio` - Update portfolio state
- `GET /portfolio` - Get all portfolio states
- `GET /portfolio/{strategy_name}` - Get specific strategy state

## Using the API from Strategies

Strategies communicate with the API via internal cluster DNS. Strategies are **stateless** and call the API for all operations. The `Scheduler` base class automatically handles all API integration.

**Example: SPXL Strategy**

```python
from SureshotSDK.Scheduler import Scheduler

class ilSPXLScheduler(Scheduler):
    name = "IncredibleLeverage_SPXL"

    def __init__(self):
        # No Portfolio object needed - API manages state
        super().__init__(portfolio=None, strategy_name=self.name)

    def on_data(self, price):
        current_sma = self.sma.get_value()

        # Check invested status from API
        if self.invested:
            if price < current_sma:
                self.sell_all(self.positionSymbol)  # Calls API
        else:
            if price > current_sma:
                self.buy_all(self.positionSymbol)   # Calls API
```

```python
import requests

API_URL = "http://efficientfrontier-api:8000"

# Execute buy_all order
order = {
    "strategy_name": "IncredibleLeverage_SPXL",
    "symbol": "SPXL",
    "price": 150.50
}
response = requests.post(f"{API_URL}/orders/buy_all", json=order)
```

## Trading Modes

The API supports two trading modes controlled by the `TRADING_MODE` environment variable:

**PAPER Mode (default):**

- Orders are recorded in the database without being sent to a brokerage
- Orders marked as `EXECUTED` immediately
- Set: `TRADING_MODE=PAPER`

**LIVE Mode:**

- Orders are sent to IBKR for real execution
- Orders marked as `PENDING` until filled by broker
- Requires IBKR credentials
- Set: `TRADING_MODE=LIVE`

Change the mode in the deployment yaml:

```yaml
- name: TRADING_MODE
  value: "PAPER" # or "LIVE"
```

## Deployment

**Build containers from project root:**

```bash
# Build EfficientFrontier API
docker build -t portfolio_efficientfrontier:latest -f portfolio_IL_efficientfrontier/EfficientFrontier/Dockerfile \
  portfolio_IL_efficientfrontier/

# Build each strategy
docker build -t incredibleleverage:spxl \
  -f portfolio_IL_efficientfrontier/IncredibleLeverageSPXL/Dockerfile .
docker build ...

# Push to registry (if using remote)
docker push portfolio_efficientfrontier:latest
docker push incredibleleverage:spxl
docker push ...
```

**Deploy to Kubernetes:**

```bash
# Build API
cd EfficientFrontier
kubectl apply -f EfficientFrontier.yaml

# Check status
kubectl get pods -l app=efficientfrontier

# View logs
kubectl logs <pod-name> -c efficientfrontier-api
kubectl logs <pod-name> -c incredibleleverage-spxl
```
