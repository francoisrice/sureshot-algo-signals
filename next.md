# Next

**Add a fast moving strategy to the portfolio for testing**
**--> Refine Fast moving strategy to prep for LIVE trading**
**--> Create Backtesting logic & system to speed up idea-to-robust-strategy timeline**
**Then, Add a vault service to the production deployment, centralized logging, and deploy to a k8s cluster for LIVE trading**

- Make sure the logic for prices and executions are correct [...]
- [x] Setup Hashicorp Vault to pass secrets into Containers
  - [] Integrate 1Password, so Vault can Auto-unseal keys after restart
- [...] Make sure trades can be placed end-to-end through IBKR client and TradingStrategy correctly
- [] Add vault to Prod deployment
- [] ...Run on server...
- Used a centralized logging service across k8s cluster
  - ...
- Paper Trading [X]
- Backtesting [...]
  - [x] Manually find investment periods for IL_efficientfrontier portfolio
  - [x] Calculate P/L for each period
  - [] Run backtest and compare again manual P/L with manual P/L as source of truth
    - Get strategies to buy at the first valid signal [X]
    - Get 5+ years of data on Polygon.io [X]
  - [...] Fix backtest code until backtests are correct
- Discretionary Trading WebApp


---

- Create testset.csv to automate testing of optimization/evaluate.py
- 


---

- Terraform for Vault and deployments?
- Connect Portfolio.buy_all() to PostgresQL/SQLite for Paper Trading [x]
  - Connect Portfolio.buy_all() to IBKR and send live based on environment setting/feature flag