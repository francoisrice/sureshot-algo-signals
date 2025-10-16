# Next

- Make sure the logic for prices and executions are correct [...]
  - Create unit and integration tests to ensure these stay correct [...]
    [x] - Setup Hashicorp Vault to pass secrets into Containers
    [] - Integrate 1Password, so Vault can Auto-unseal keys after restart
- Move SureshotSDK outside of automation

---

- Terraform for Vault and deployments?
- Connect Portfolio.buy_all() to PostgresQL/SQLite for Paper Trading
  - Connect Portfolio.buy_all() to IBKR and send live based on environment setting/feature flag
-

How should the vault keys and root token in vault-keys.json be stored securely? -> 1Password server that the application can access or Key Management service

1. Create tests to validate functionality of the project [X]
   1b. Cleanup the tests. Keep only business logic and meaningful tests.

   - SMA [X]
   - Portfolio
   - PolygonClient

2. Recreate monorepo and move SureshotSDK outside of automation
   Can you please reconfigure the monorepo created in automation/ to make the root of this project the monorepo, and move
   SureshotSDK outside of automation/ ? Please make sure to update all references and imports of SureshotSDK in the files
   inside automation.

3. Revalidate project by running all tests
