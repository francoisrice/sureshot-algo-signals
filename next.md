# Next

Currently setting warm-up variables manually - need automated solution...

Optimization & Backtesting are now usable. Configure them for more strategy types. While creating more strategies.
    - Implement ORB strategy
        _ Add /orders/short_sell_all to MultiStrategyAPI


- Add a fast moving strategy to the portfolio for Forward testing
    - Need source for real-time minute data (not financially viable through Massive)
- Then, Add a vault service to the production deployment, centralized logging, and deploy to a k8s cluster for LIVE trading

---

- Add vault to Prod deployment
- Used a centralized logging service across k8s cluster

---

Backtesting
Optimization
Automated Live Trading
Backtest/Optimization Application


---

- Terraform for Vault and deployments?
- Integrate 1Password, so Vault can Auto-unseal keys after restart