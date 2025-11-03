# HashiCorp Vault Deployment for Kubernetes

This directory contains Kubernetes manifests for deploying HashiCorp Vault with persistent storage to manage secrets for the Sureshot Algo trading system.

## Architecture

- **Vault StatefulSet**: Single-node Vault server with persistent storage
- **Persistent Storage**: 10Gi persistent volume for data durability
- **Kubernetes Auth**: Native Kubernetes authentication for pods
- **Secret Management**: Centralized secret storage replacing environment variables

## Prerequisites

- Kubernetes cluster (v1.20+)
- `kubectl` configured to access your cluster
- `jq` installed for JSON parsing (initialization script)

## Deployment Steps

### 1. Deploy Vault

```bash
# Deploy all Vault resources
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-storage.yaml
kubectl apply -f 02-configmap.yaml
kubectl apply -f 03-statefulset.yaml
kubectl apply -f 04-service.yaml

# Or deploy all at once
kubectl apply -f .
```

### 2. Initialize Vault

```bash
# Run the initialization script
./init-vault.sh

# This will:
# - Wait for Vault pod to be ready
# - Initialize Vault with 5 key shares (3 required to unseal)
# - Save unseal keys and root token to vault-keys.json
# - Automatically unseal Vault
```

**⚠️ IMPORTANT**: Store `vault-keys.json` securely! You'll need these keys to unseal Vault after pod restarts.

### 3. Configure Vault

```bash
# Get the root token from vault-keys.json
ROOT_TOKEN=$(cat vault-keys.json | jq -r '.root_token')

# Run the configuration script
ROOT_TOKEN=$ROOT_TOKEN ./configure-vault.sh

# This will:
# - Enable KV secrets engine
# - Store your Polygon API key
# - Enable Kubernetes authentication
# - Create policies and roles for application access
```

### 4. Verify Deployment

```bash
# Check Vault status
kubectl exec -n vault vault-0 -- vault status

# Port-forward to access Vault UI
kubectl port-forward -n vault svc/vault 8200:8200

# Open http://localhost:8200 in your browser
# Login with the root token from vault-keys.json
```

## Adding Secrets

### Via CLI

```bash
# Get Vault pod name
VAULT_POD=$(kubectl get pods -n vault -l app=vault -o jsonpath='{.items[0].metadata.name}')

# Login with root token
kubectl exec -n vault -it $VAULT_POD -- sh
export VAULT_TOKEN=<your-root-token>

# Add a secret
vault kv put secret/sureshot-algo/polygon api_key=your_polygon_api_key

# Add more secrets
vault kv put secret/sureshot-algo/database \
  host=db.example.com \
  username=trader \
  password=secure_password

# List secrets
vault kv list secret/sureshot-algo

# Read a secret
vault kv get secret/sureshot-algo/polygon
```

### Via Port-Forward and UI

```bash
kubectl port-forward -n vault svc/vault 8200:8200
# Navigate to http://localhost:8200
# Use the Vault UI to add/manage secrets
```

## Using Secrets in Applications

### Method 1: Vault Agent Injector (Recommended)

See `example-app-with-vault.yaml` for the annotation-based approach:

```yaml
annotations:
  vault.hashicorp.com/agent-inject: "true"
  vault.hashicorp.com/role: "sureshot-algo"
  vault.hashicorp.com/agent-inject-secret-polygon: "secret/data/sureshot-algo/polygon"
```

### Method 2: Init Container

The init container fetches secrets and writes them to a shared volume:

```yaml
initContainers:
  - name: vault-init
    image: hashicorp/vault:1.15.2
    # Fetches secrets using Kubernetes auth
```

### Method 3: Python Client (HVAC)

Install in your application:

```bash
pip install hvac
```

Python code:

```python
import hvac
import os

# Authenticate with Kubernetes
client = hvac.Client(url='http://vault.vault.svc.cluster.local:8200')

# Read service account JWT
with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
    jwt = f.read()

# Login
client.auth.kubernetes.login(
    role='sureshot-algo',
    jwt=jwt
)

# Fetch secret
secret = client.secrets.kv.v2.read_secret_version(
    path='sureshot-algo/polygon'
)

polygon_api_key = secret['data']['data']['api_key']
```

## Unsealing Vault After Restart

If the Vault pod restarts, it will be in a sealed state:

```bash
# Get unseal keys from vault-keys.json
UNSEAL_KEY_1=$(cat vault-keys.json | jq -r '.unseal_keys_b64[0]')
UNSEAL_KEY_2=$(cat vault-keys.json | jq -r '.unseal_keys_b64[1]')
UNSEAL_KEY_3=$(cat vault-keys.json | jq -r '.unseal_keys_b64[2]')

# Unseal Vault (need 3 keys)
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_1
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_2
kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_3
```

## Backup and Recovery

### Backup Vault Data

```bash
# Create a backup of the persistent volume
kubectl exec -n vault vault-0 -- tar czf /tmp/vault-backup.tar.gz /vault/data

# Copy backup to local machine
kubectl cp vault/vault-0:/tmp/vault-backup.tar.gz ./vault-backup-$(date +%Y%m%d).tar.gz
```

### Restore from Backup

```bash
# Copy backup to pod
kubectl cp ./vault-backup.tar.gz vault/vault-0:/tmp/vault-backup.tar.gz

# Extract backup
kubectl exec -n vault vault-0 -- tar xzf /tmp/vault-backup.tar.gz -C /
```

## Production Considerations

### 1. Enable TLS

Update `02-configmap.yaml`:

```hcl
listener "tcp" {
  tls_disable = 0
  tls_cert_file = "/vault/tls/tls.crt"
  tls_key_file = "/vault/tls/tls.key"
}
```

### 2. High Availability

For production, consider running Vault in HA mode with Consul or Raft storage backend.

### 3. Auto-Unseal

Configure auto-unseal using cloud KMS:

- AWS KMS
- GCP Cloud KMS
- Azure Key Vault

### 4. Monitoring

Enable Prometheus metrics (already configured in the service):

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8200"
  prometheus.io/path: "/v1/sys/metrics"
```

### 5. Audit Logging

Enable audit logging:

```bash
vault audit enable file file_path=/vault/logs/audit.log
```

## Troubleshooting

### Vault pod not starting

```bash
kubectl logs -n vault vault-0
kubectl describe pod -n vault vault-0
```

### Vault is sealed

```bash
kubectl exec -n vault vault-0 -- vault status
# If sealed=true, follow unsealing steps above
```

### Permission denied accessing secrets

```bash
# Check the policy
kubectl exec -n vault vault-0 -- vault policy read sureshot-algo-policy

# Check the role
kubectl exec -n vault vault-0 -- vault read auth/kubernetes/role/sureshot-algo
```

### Storage issues

```bash
# Check PVC status
kubectl get pvc -n vault

# Check PV
kubectl get pv
```

## Security Best Practices

1. **Never commit vault-keys.json to version control**
2. **Store unseal keys in separate secure locations**
3. **Rotate root token regularly**
4. **Use separate policies for different applications**
5. **Enable audit logging**
6. **Use TLS in production**
7. **Implement backup strategy**
8. **Use namespace isolation**

## Clean Up

```bash
# Delete Vault deployment
kubectl delete -f .

# Delete PVC (this will delete stored data!)
kubectl delete pvc -n vault vault-storage

# Delete namespace
kubectl delete namespace vault
```

## Next Steps

1. Deploy Vault: `kubectl apply -f .`
2. Initialize: `./init-vault.sh`
3. Configure: `ROOT_TOKEN=<token> ./configure-vault.sh`
4. Update your application deployments to use Vault
5. Test secret retrieval
6. Set up monitoring and backup

## References

- [Vault Documentation](https://www.vaultproject.io/docs)
- [Vault Kubernetes Auth](https://www.vaultproject.io/docs/auth/kubernetes)
- [Vault Agent Injector](https://www.vaultproject.io/docs/platform/k8s/injector)
