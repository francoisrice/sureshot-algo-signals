# Next

- Make sure the logic for prices and executions are correct [...]
  - [x] Create unit and integration tests to ensure these stay correct
- [x] Setup Hashicorp Vault to pass secrets into Containers
  - [] Integrate 1Password, so Vault can Auto-unseal keys after restart
- [x] Move SureshotSDK outside of automation

---

- Terraform for Vault and deployments?
- Connect Portfolio.buy_all() to PostgresQL/SQLite for Paper Trading
  - Connect Portfolio.buy_all() to IBKR and send live based on environment setting/feature flag

How should the vault keys and root token in vault-keys.json be stored securely? -> 1Password server that the application can access or Key Management service
