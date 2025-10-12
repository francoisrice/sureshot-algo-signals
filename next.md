# Next

- Make sure the logic for prices and executions are correct
  - Create unit and integration tests to ensure these stay correct
    [x] - Setup Hashicorp Vault to pass secrets into Containers
    [] - Integrate 1Password, so Vault can Auto-unseal keys after restart
- Move SureshotSDK outside of automation
- Terraform for Vault and deployments?

How should the vault keys and root token in vault-keys.json be stored securely? -> 1Password server that the application can access or Key Management service
