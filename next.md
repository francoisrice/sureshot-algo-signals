# Next

**The updates to the Portfolio API are tested and working.**
**Now, Add a vault service to the production deployment, connect paper trading to fully test the connection, deploy to a k8s cluster**

- Make sure the logic for prices and executions are correct [...]
  - [x] Create unit and integration tests to ensure these stay correct
- [x] Setup Hashicorp Vault to pass secrets into Containers
  - [] Integrate 1Password, so Vault can Auto-unseal keys after restart
- [x] Move SureshotSDK outside of automation
- Live Trading
  - [x] Automate IBKR login <- will this work from a deployment cluster?
  - 1. [x] Test that orders are placed successfully with buy method
  - 2. [x]Create methods to check positions in IBKR
  - 3. [x] Create tests around IBKR client
    - If stop_loss returns first call as > 299
    - If stop_loss returns 3 confirmation messages with field 'id'
    - If buy order returns first call as > 299
    - If buy order returns 3 confirmation messages with field 'id'
    - If sell_order returns first call as > 299
    - If sell_order returns 3 confirmation messages with field 'id'
  - 1. [x] Confirm responses with 'id' for buys, sells, and verify for stop_orders
  - 2. [...] Make sure trades can be placed end-to-end through IBKR client and TradingStrategy correctly and that [x] refreshing the connection is automatic
  - 3. [...] ...Portfolio...
  - 4. ...Run on server...
- Used a centralized logging service across k8s cluster
  - ...
- Paper Trading

  - Create SQLite/PostgresQL client
  - Add sqlite/ or postgresql/ directory to k8s

- Backtesting

---

To get IBKR working

- Get process down for logging in [x] and making requests [...]
  - Launch portal with bash command
  - Use automation to fill in portal fields[X]; MFA integration [x]
  -
- Use tools to login to ibkr from single portal
- Automate the process in a single function call or script
- Run the script from a container
- Run the script from a K8s deployment

---

- Terraform for Vault and deployments?
- Connect Portfolio.buy_all() to PostgresQL/SQLite for Paper Trading
  - Connect Portfolio.buy_all() to IBKR and send live based on environment setting/feature flag

How should the vault keys and root token in vault-keys.json be stored securely? -> 1Password server that the application can access or Key Management service
