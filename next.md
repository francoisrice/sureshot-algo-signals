# Next

Currently setting warm-up variables manually - need automated solution...

Optimization & Backtesting are now usable. Configure them for more strategy types. While creating more strategies.

ORB backtesting works, but the ORB strategy is not robust/profitable...

ORB scanner is now parallelized & pulls daily bars from memory (~76MB). Allows for processing ~200 stocks/second from cache.

- Find regime where ORB is profitable
    - Andrew Aziz: does he have clues on profitable ORB?
    -> Try trading just TQQQ & SPXL
- Run simultaneous backtests and optimization -> Run backtests and optimization on cloud infra
- Short Iron Condor/Butterfly
- Grid Trading

- Add a fast moving strategy to the portfolio for Forward testing
    - Need source for real-time minute data (not financially viable through Massive) <- Webscrapper on nasdaq.com
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