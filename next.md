# Next

Currently setting warm-up variables manually - need automated solution...

Optimization & Backtesting are now usable. Configure them for more strategy types. While creating more strategies.


ORB scanner is now parallelized & pulls daily bars from memory (~76MB). Allows for processing ~200 stocks/second from cache.

Implemented ORB with TQQQ - Backtests and optimizations look profitable

**1. Run ORB and IncredibleLeverage LIVE**
When you pick a registry, swap <YOUR_REGISTRY_TBD> in 
  live_trading_infrastructure/README.md and update the image: fields in the two K8s deployment manifests.
  Remaining before deployment:
  1. Add BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID to the K8s secrets or deployment env vars for the
  multistrategy-api container (which owns the Browserbase session via TradingStrategy._data_fetcher)              
  2. Build and push sureshotcapital/multi-strategy-api:latest and sureshotcapital/orb-aziz-tqqq:latest
  3. Run the Ansible playbook to sync manifests and apply to the worker node
**1. Run multiple strategies and optimizations at the same time <- Cloud infrastrucuture with multiple nodes and container clusters**

_Refactor trading code to only reauth to IBKR when needed and only through the Client Portal container. Playwright doesn't need to be a dependency for the Portfolio or TradingStrategy container.
_Add keys to the orchestrator node
_Implement the Unsealing k8s Secrets and Vault
_Is bitnami a good enough container image for the trading?

- Create date-range integration tests for IncredibleLeverageSPXL, ORB_HighVolume, and MultipointHillClimbing optimization
- **Short Iron Condor/Butterfly**
- Grid Trading

- Add a fast moving strategy to the portfolio for Forward testing
    - Need source for real-time minute data (not financially viable through Massive) <- Webscrapper on nasdaq.com
- Then, Add a vault service to the production deployment, centralized logging, and deploy to a k8s cluster for LIVE trading


---

- Add vault to Prod deployment
- Used a centralized logging service across k8s cluster
- Integrate OpenClaw with a $$ cap to iterate through implementing strategies.
  - Use the backtesting & optimization to find new strategies
  - Scan the repo and test code against test scripts and delete unused code
  - Implement code into the repo for new strategies: Options, Bond carry, Futures, FundamentalsS

---

Backtesting
Optimization
Automated Live Trading
Backtest/Optimization Application


---

- Terraform for Vault and deployments?
- Integrate 1Password, so Vault can Auto-unseal keys after restart