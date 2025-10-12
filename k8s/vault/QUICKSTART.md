# Quick Start Guide - Vault Integration

This guide will get you up and running with Vault in 5 minutes.

## Step 1: Deploy Vault (2 minutes)

```bash
cd k8s/vault

# Deploy all Vault resources
kubectl apply -f .

# Wait for Vault to be ready
kubectl wait --for=condition=ready pod -l app=vault -n vault --timeout=300s
```

## Step 2: Initialize and Unseal Vault (1 minute)

```bash
# Initialize Vault (creates unseal keys and root token)
./init-vault.sh

# IMPORTANT: Save the vault-keys.json file securely!
# You'll need it if Vault ever needs to be unsealed
```

## Step 3: Configure Vault with Your Secrets (2 minutes)

```bash
# Get root token from the initialization
ROOT_TOKEN=$(cat vault-keys.json | jq -r '.root_token')

# Run configuration script (will prompt for Polygon API key)
ROOT_TOKEN=$ROOT_TOKEN ./configure-vault.sh
```

That's it! Vault is now configured and ready to use.

## Using Vault in Your Application

### Option 1: Python Code (Recommended for Development)

```python
from SureshotSDK.Polygon import PolygonClient

# Automatically fetches API key from Vault
client = PolygonClient(use_vault=True)

# Or use the vault client directly
from SureshotSDK.vault_client import VaultClient

vault = VaultClient()
polygon_key = vault.get_polygon_api_key()
```

### Option 2: Kubernetes Deployment with Init Container

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-trading-app
spec:
  template:
    spec:
      serviceAccountName: sureshot-algo
      initContainers:
        - name: vault-init
          image: hashicorp/vault:1.15.2
          command: ["/bin/sh", "-c"]
          args:
            - |
              # Login and fetch secret
              VAULT_TOKEN=$(vault write -field=token auth/kubernetes/login \
                role=sureshot-algo \
                jwt=@/var/run/secrets/kubernetes.io/serviceaccount/token)

              export VAULT_TOKEN

              # Write API key to shared volume
              vault kv get -field=api_key secret/sureshot-algo/polygon > /secrets/POLYGON_API_KEY
          env:
            - name: VAULT_ADDR
              value: "http://vault.vault.svc.cluster.local:8200"
          volumeMounts:
            - name: secrets
              mountPath: /secrets
      containers:
        - name: app
          image: my-app:latest
          command: ["/bin/sh", "-c"]
          args:
            - |
              export POLYGON_API_KEY=$(cat /secrets/POLYGON_API_KEY)
              python main.py
          volumeMounts:
            - name: secrets
              mountPath: /secrets
              readOnly: true
      volumes:
        - name: secrets
          emptyDir:
            medium: Memory
```

### Option 3: Direct Environment Variable (Simple)

```bash
# Port forward to Vault
kubectl port-forward -n vault svc/vault 8200:8200 &

# Get secret
export VAULT_TOKEN=$(cat vault-keys.json | jq -r '.root_token')
export VAULT_ADDR=http://localhost:8200

# Fetch and export
export POLYGON_API_KEY=$(vault kv get -field=api_key secret/sureshot-algo/polygon)

# Run your app
python main.py
```

## Common Tasks

### Add a New Secret

```bash
VAULT_POD=$(kubectl get pods -n vault -l app=vault -o jsonpath='{.items[0].metadata.name}')
ROOT_TOKEN=$(cat vault-keys.json | jq -r '.root_token')

kubectl exec -n vault -it $VAULT_POD -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault kv put secret/sureshot-algo/database \
    host=db.example.com \
    username=trader \
    password=secret123
"
```

### View All Secrets

```bash
kubectl exec -n vault -it $VAULT_POD -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault kv list secret/sureshot-algo
"
```

### Access Vault UI

```bash
# Port forward
kubectl port-forward -n vault svc/vault 8200:8200

# Open browser to http://localhost:8200
# Login with root token from vault-keys.json
```

### Unseal Vault After Pod Restart

```bash
UNSEAL_KEY_1=$(cat vault-keys.json | jq -r '.unseal_keys_b64[0]')
UNSEAL_KEY_2=$(cat vault-keys.json | jq -r '.unseal_keys_b64[1]')
UNSEAL_KEY_3=$(cat vault-keys.json | jq -r '.unseal_keys_b64[2]')

kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_3
```

## Troubleshooting

### Vault is sealed

```bash
# Check status
kubectl exec -n vault vault-0 -- vault status

# If sealed=true, run unseal commands above
```

### Can't connect to Vault from pod

```bash
# Test connectivity
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  wget -O- http://vault.vault.svc.cluster.local:8200/v1/sys/health
```

### Permission denied

```bash
# Check if service account exists
kubectl get sa sureshot-algo

# Check if role exists in Vault
kubectl exec -n vault vault-0 -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault read auth/kubernetes/role/sureshot-algo
"
```

## Security Notes

1. **Store vault-keys.json securely** - Anyone with these keys can unseal Vault
2. **Rotate the root token** - Don't use it for regular operations
3. **Use separate roles** for different applications
4. **Enable audit logging** in production
5. **Enable TLS** in production

For more details, see [README.md](./README.md)
