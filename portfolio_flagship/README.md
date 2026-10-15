# Flagship Portfolio

Sureshot's flagship portfolio: three strategies that share one portfolio API, which allocates capital and routes orders.

## Strategies

| Strategy | Folder | `STRATEGY_NAME` | Container / image | Summary |
|---|---|---|---|---|
| Sidewinder | `sidewinder/` | `Sidewinder` | `sidewinder` / `sureshotcapital/sidewinder` | Opening range breakout on TQQQ: long or short from the first 5-minute range, stop at the opposite side of the range, 10x take-profit, flat by end of day |
| ClusterBarrage | `cluster_barrage/` | `ClusterBarrage` | `cluster-barrage` / `sureshotcapital/cluster-barrage` | Six Sidewinder legs entering 5, 10, 15, 20, 30 and 60 minutes after the open, each risking 1/6 as much, netted into one TQQQ position |
| SiegeEngine | `siege_engine/` | `SiegeEngine` | `siege-engine` / `sureshotcapital/flagship-siege-engine` | Volatility-decay harvester: long GLDM, short SHNY at 3:1, 5% stop-loss, checked once a day at 3:50pm ET (see `siege_engine/SPEC.md`) |

Sidewinder was ported from `portfolio_multi_strategy/ORB_Aziz_TQQQ`, ClusterBarrage from `portfolio_multi_strategy/ORB_Hydra`, and SiegeEngine from `portfolio_multi_strategy/SiegeEngine`.

## Naming conventions

Each strategy name has to match in several places:

- **Folder name** is snake_case, as `CLAUDE.md` requires. `backtest.py` imports `portfolio_flagship.<folder>.main` and picks the class whose name matches the folder once both are lowercased and underscores are removed. For example, `cluster_barrage/` must contain `class ClusterBarrage`.
- **Class name and `STRATEGY_NAME`** are both the CamelCase strategy name. `STRATEGY_NAME` is the key for the strategy's rows in the portfolio API database.
- **`PORTFOLIO_STRATEGIES`** in `deployment.yaml`. This comma-separated list must use the `STRATEGY_NAME` values.
- **Container and image names** use the kebab-case form of the folder name (`cluster_barrage` becomes `cluster-barrage`).

Every Kubernetes resource and image built from this folder has a `flagship` name: deployment `flagship-portfolio`, label `app: flagship`, service and container `flagship-api`, and database `flagship`. That keeps it separate from the `multistrategy-*` resources that `portfolio_multi_strategy` runs live. SiegeEngine's image is called `flagship-siege-engine` because `siege-engine` already belongs to the `portfolio_multi_strategy` copy.

## Layout

```
portfolio_flagship/
├── api/                  # Portfolio API: allocation, orders, positions, IBKR routing
├── sidewinder/           # main.py + Dockerfile
├── cluster_barrage/      # main.py + Dockerfile
├── siege_engine/         # main.py + Dockerfile + SPEC.md
├── deployment.yaml       # Kubernetes deployment + service
└── README.md
```

## Backtesting

Set these values in the root-level `backtest.py`, then run `python backtest.py`:

```python
PORTFOLIO = "portfolio_flagship"
STRATEGY = "sidewinder"   # or cluster_barrage, siege_engine
```

## Local development

```bash
# Portfolio API (from the repo root; uses sqlite:///./multistrategy.db unless DATABASE_URL is set)
uvicorn portfolio_flagship.api.main:app --reload --port 8000

# Each strategy in its own terminal
export TRADING_MODE=PAPER API_URL=http://localhost:8000
python portfolio_flagship/sidewinder/main.py
python portfolio_flagship/cluster_barrage/main.py
python portfolio_flagship/siege_engine/main.py
```

## Kubernetes deployment

### 1. Build and push the images (from the repo root)

```bash
docker build -f portfolio_flagship/api/Dockerfile -t sureshotcapital/flagship-api:latest .
docker build -f portfolio_flagship/sidewinder/Dockerfile -t sureshotcapital/sidewinder:latest .
docker build -f portfolio_flagship/cluster_barrage/Dockerfile -t sureshotcapital/cluster-barrage:latest .
docker build -f portfolio_flagship/siege_engine/Dockerfile -t sureshotcapital/flagship-siege-engine:latest .

for image in flagship-api sidewinder cluster-barrage flagship-siege-engine; do
  docker push sureshotcapital/$image:latest
done
```

### 2. Create the database (once)

The shared Postgres instance only creates the `multistrategy` database automatically. Create `flagship` before the first deploy:

```bash
microk8s kubectl exec -n trading deploy/postgres -- psql -U postgres -c 'CREATE DATABASE flagship;'
```

### 3. Apply and check

```bash
microk8s kubectl apply -f portfolio_flagship/deployment.yaml
microk8s kubectl get pods -n trading -l app=flagship
microk8s kubectl logs -n trading -l app=flagship -c flagship-api
microk8s kubectl logs -n trading -l app=flagship -c sidewinder
```

The deployment starts at `replicas: 0`. The market-open and market-close CronJobs in `live_trading_infrastructure/k8s/cronjobs/` scale only `deployment/multistrategy-portfolio` so far, so they won't start this portfolio.

Secrets (`ib-credentials`, `browserbase-credentials`), capital allocation, API endpoints and environment variables are the same as in `portfolio_multi_strategy`. See `portfolio_multi_strategy/README.md` and `api/README.md`.
