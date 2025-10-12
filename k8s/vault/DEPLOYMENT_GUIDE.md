# HashiCorp Vault Deployment Guide

**Complete step-by-step guide to deploy, initialize, and configure Vault from scratch**

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Understanding Vault Components](#understanding-vault-components)
3. [Deployment Steps](#deployment-steps)
4. [Initialization & Unsealing](#initialization--unsealing)
5. [Configuration](#configuration)
6. [Adding Secrets](#adding-secrets)
7. [Verification](#verification)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

- `kubectl` or `microk8s` installed and configured
- `jq` for JSON parsing: `sudo apt install jq`
- Access to Kubernetes cluster with admin privileges
- Storage provisioner enabled (for microk8s: hostpath-storage)

### Verify Prerequisites

```bash
# Check Kubernetes access
microk8s kubectl get nodes

# Check storage class is available
microk8s kubectl get storageclass

# Should show: microk8s-hostpath (default)
```

**Why?** Vault requires persistent storage to survive pod restarts. Without storage, all data would be lost.

---

## Understanding Vault Components

Before deploying, understand what each component does:

### 1. **Namespace**

- Isolates Vault resources from other applications
- Provides security boundary and resource organization

### 2. **ConfigMap**

- Contains Vault configuration file (vault.hcl)
- Defines storage backend, listener settings, and security options
- Mounted into the Vault pod at runtime

### 3. **StatefulSet**

- Ensures stable pod identity (vault-0)
- Manages persistent storage attachment
- Guarantees ordered deployment and scaling

### 4. **PersistentVolume**

- Stores Vault's encrypted data
- Survives pod deletions and restarts
- Contains: encryption keys, policies, secrets, audit logs

### 5. **Service**

- Provides network access to Vault
- ClusterIP: Internal cluster communication
- Internal service: Required for StatefulSet DNS

### 6. **ServiceAccount & RBAC**

- Allows Vault to authenticate with Kubernetes API
- Required for Kubernetes authentication method

---

## Deployment Steps

### Step 1: Create Namespace and RBAC

```bash
cd /home/user/Code_After_2025/projects/sureshot-algo-signals/k8s/vault

microk8s kubectl apply -f 00-namespace.yaml
```

**What this does:**

- Creates `vault` namespace
- Creates `vault` ServiceAccount
- Binds ServiceAccount to `system:auth-delegator` role

**Why it's needed:**

- Isolates Vault resources
- Grants Vault permission to validate Kubernetes tokens
- Required for Kubernetes authentication method to work

**Verify:**

```bash
microk8s kubectl get namespace vault
microk8s kubectl get serviceaccount -n vault
microk8s kubectl get clusterrolebinding vault-server-binding
```

### Step 2: Create Configuration

```bash
microk8s kubectl apply -f 02-configmap.yaml
```

**What this does:**

- Creates ConfigMap with vault.hcl configuration
- Sets `disable_mlock = true` (required for containers)
- Configures file storage backend at `/vault/data`
- Sets up TCP listener on port 8200

**Why it's needed:**

- Vault needs configuration to know how to store data
- `disable_mlock` prevents memory locking errors in containers
- File backend provides persistent storage

**Key configuration options:**

```hcl
disable_mlock = true        # Allow running in containers
storage "file" {            # Use file-based storage (simple, good for single-node)
  path = "/vault/data"      # Where data is stored in the container
}
listener "tcp" {            # HTTP API listener
  address = "0.0.0.0:8200"  # Listen on all interfaces
  tls_disable = 1           # Disable TLS (enable in production!)
}
```

**Verify:**

```bash
microk8s kubectl get configmap -n vault
microk8s kubectl describe configmap vault-config -n vault
```

### Step 3: Deploy StatefulSet

```bash
microk8s kubectl apply -f 03-statefulset.yaml
```

**What this does:**

- Creates StatefulSet named `vault`
- Provisions persistent volume claim (10Gi)
- Deploys vault-0 pod
- Mounts config and data volumes

**Why StatefulSet instead of Deployment?**

- Stable network identity (vault-0)
- Persistent storage automatically attached
- Ordered, graceful scaling and updates
- Required for Vault's data consistency

**Important settings:**

```yaml
replicas: 1 # Single instance (HA requires 3+)
storageClassName: microk8s-hostpath # Must match available storage
resources:
  requests:
    memory: "256Mi" # Minimum memory
    cpu: "250m" # Minimum CPU
  limits:
    memory: "512Mi" # Maximum memory
    cpu: "500m" # Maximum CPU
```

**Verify:**

```bash
# Check StatefulSet
microk8s kubectl get statefulset -n vault

# Check pod (will not be READY yet - this is normal)
microk8s kubectl get pods -n vault

# Check persistent volume
microk8s kubectl get pvc -n vault

# View pod logs
microk8s kubectl logs -n vault vault-0
```

**Expected state:** Pod running but not ready (0/1). Logs should show:

```
"security barrier not initialized"
"seal configuration missing, not initialized"
```

This is **normal** - Vault needs initialization.

### Step 4: Create Services

```bash
microk8s kubectl apply -f 04-service.yaml
```

**What this does:**

- Creates `vault` service (ClusterIP) for API access
- Creates `vault-internal` service (Headless) for StatefulSet DNS

**Why both services?**

- `vault` service: Standard access point for applications
- `vault-internal` service: Enables pod-to-pod communication (required for HA)

**Verify:**

```bash
microk8s kubectl get service -n vault

# Test DNS resolution (from another pod)
microk8s kubectl run test --rm -it --image=busybox --restart=Never -- \
  nslookup vault.vault.svc.cluster.local
```

---

## Initialization & Unsealing

### Understanding Vault's Security Model

**Vault starts in three states:**

1. **Uninitialized** (first start)

   - No encryption keys generated
   - Cannot store or retrieve data
   - Requires initialization

2. **Initialized but Sealed** (after restart)

   - Encryption keys exist but are encrypted
   - Cannot access data
   - Requires unsealing with keys

3. **Unsealed** (operational)
   - Encryption keys in memory
   - Can read/write secrets
   - Fully functional

**Why this design?**

- Even if someone steals the persistent volume, data is encrypted
- Multiple people needed to unseal (no single point of compromise)
- Automatic sealing on restart adds security layer

### Step 5: Initialize Vault

```bash
# Check current status
microk8s kubectl exec -n vault vault-0 -- vault status

# Should show: Initialized: false, Sealed: true
```

**Run initialization:**

```bash
cd /home/user/Code_After_2025/projects/sureshot-algo-signals/k8s/vault

./init-vault-microk8s.sh
```

**What this script does:**

1. **Waits for pod to be running**

   - Ensures Vault process is ready

2. **Checks if already initialized**

   - Prevents accidentally re-initializing
   - Re-initialization would make existing data unrecoverable

3. **Initializes with Shamir's Secret Sharing**

   ```
   -key-shares=5      # Generate 5 key fragments
   -key-threshold=3   # Need 3 fragments to unseal
   ```

4. **Saves keys to vault-keys.json**

   - Contains 5 unseal keys
   - Contains root token (admin password)
   - **MUST BE STORED SECURELY**

5. **Unseals Vault automatically**
   - Applies 3 of the 5 keys
   - Vault becomes operational

**What are unseal keys?**

- Master key is split into 5 fragments using Shamir's algorithm
- Any 3 fragments can reconstruct the master key
- Master key decrypts the encryption key
- Encryption key decrypts your secrets

**Why 5 keys with 3 required?**

- No single person can unseal Vault alone
- Allows 2 keys to be lost/unavailable
- Balances security with operational flexibility

**Output example:**

```
Vault keys saved to vault-keys.json
⚠️  IMPORTANT: Store vault-keys.json in a secure location!

Root Token: xxxxxxxxxxxxxxxxxxxxxxx

✅ Vault is now unsealed and ready to use
```

**Verify:**

```bash
microk8s kubectl exec -n vault vault-0 -- vault status

# Should show:
# Initialized: true
# Sealed: false
# Total Shares: 5
# Threshold: 3
```

**Pod should now be ready:**

```bash
microk8s kubectl get pods -n vault

# Should show: vault-0   1/1   Running
```

### Step 6: Secure the Keys (CRITICAL)

**The vault-keys.json file contains:**

```json
{
  "unseal_keys_b64": [
    "key1...", // Unseal key 1
    "key2...", // Unseal key 2
    "key3...", // Unseal key 3
    "key4...", // Unseal key 4
    "key5..." // Unseal key 5
  ],
  "root_token": "hvs...." // Root admin token
}
```

**IMMEDIATELY:**

1. **Copy to 1Password** (manually for now)

   - Create new item for each unseal key
   - Create separate item for root token
   - Tag with "vault", "production", "unseal-key"

2. **Create backup**

   ```bash
   # Encrypt with GPG
   gpg --symmetric --cipher-algo AES256 vault-keys.json

   # Creates vault-keys.json.gpg
   # Store this encrypted file in multiple locations
   ```

3. **Delete the original**
   ```bash
   shred -vfz -n 10 vault-keys.json
   ```

**Why this matters:**

- Anyone with these keys can access ALL secrets in Vault
- Root token has unlimited privileges
- If lost, Vault cannot be unsealed (data is permanently inaccessible)

---

## Configuration

Now that Vault is running, configure it for use.

### Step 7: Enable Secrets Engine

```bash
# Get root token from 1Password or vault-keys.json
ROOT_TOKEN="xxxxxxxxxxxxxxxxxxxxxxx"

microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault secrets enable -path=secret kv-v2
"
```

**What this does:**

- Enables KV (Key-Value) version 2 secrets engine
- Mounts it at path `secret/`
- KV v2 provides versioning of secrets

**Why KV v2?**

- Automatic versioning (can recover old secret values)
- Soft deletes (can undelete)
- Metadata tracking (when created, who accessed)

**Verify:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault secrets list
"

# Should show: secret/ with type: kv-v2
```

### Step 8: Enable Kubernetes Authentication

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault auth enable kubernetes
"
```

**What this does:**

- Enables Kubernetes authentication method
- Allows pods to authenticate using their ServiceAccount JWT token

**Why this matters:**

- No need to distribute tokens to applications
- Pods authenticate automatically using their identity
- Tokens are short-lived and automatically rotated

**Configure Kubernetes auth:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault write auth/kubernetes/config \
    kubernetes_host=\"https://\$KUBERNETES_PORT_443_TCP_ADDR:443\"
"
```

**What this does:**

- Tells Vault where to find the Kubernetes API
- Uses environment variable that's automatically set in pods
- Vault will validate ServiceAccount tokens with this API

**Verify:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault auth list
"

# Should show: kubernetes/ method enabled
```

### Step 9: Create Access Policy

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault policy write sureshot-algo-policy - <<EOF
path \"secret/data/sureshot-algo/*\" {
  capabilities = [\"read\"]
}

path \"secret/metadata/sureshot-algo/*\" {
  capabilities = [\"list\"]
}
EOF
"
```

**What this does:**

- Creates a policy named `sureshot-algo-policy`
- Grants READ access to secrets under `secret/sureshot-algo/`
- Grants LIST access to see what secrets exist

**Understanding the paths:**

- `secret/data/sureshot-algo/*` - Actual secret data (KV v2 uses /data/)
- `secret/metadata/sureshot-algo/*` - Secret metadata (versions, creation time)

**Why policies?**

- Implement least-privilege access
- Applications only see secrets they need
- Audit trail of what each app can access

**Verify:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault policy read sureshot-algo-policy
"
```

### Step 10: Create Kubernetes Auth Role

First, create ServiceAccount for applications:

```bash
microk8s kubectl create serviceaccount sureshot-algo -n default
```

**Why?** Applications will use this identity to authenticate.

Now create the Vault role:

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault write auth/kubernetes/role/sureshot-algo \
    bound_service_account_names=sureshot-algo \
    bound_service_account_namespaces=default \
    policies=sureshot-algo-policy \
    ttl=24h
"
```

**What this does:**

- Creates a role named `sureshot-algo`
- Binds to ServiceAccount `sureshot-algo` in namespace `default`
- Assigns the `sureshot-algo-policy` policy
- Tokens valid for 24 hours

**Understanding the binding:**

- Only pods with ServiceAccount `sureshot-algo` can use this role
- Only in namespace `default` (security boundary)
- If pod is deleted/recreated, it can still authenticate

**Verify:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault read auth/kubernetes/role/sureshot-algo
"
```

---

## Adding Secrets

### Step 11: Store Your First Secret

```bash
# Example: Store Polygon API key
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv put secret/sureshot-algo/polygon \
    api_key=YOUR_API_KEY_HERE
"
```

**What this does:**

- Stores secret at path `secret/sureshot-algo/polygon`
- Key-value pair: `api_key = YOUR_API_KEY_HERE`
- Automatically encrypted before writing to disk

**Understanding secret paths:**

```
secret/                      # Secrets engine mount point
└── sureshot-algo/          # Application/project namespace
    └── polygon             # Secret name
        └── api_key         # Field within secret
```

**Why organize this way?**

- Clear hierarchy
- Easy to manage permissions
- Can have multiple fields per secret

**Add more secrets:**

```bash
# Database credentials
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv put secret/sureshot-algo/database \
    host=db.example.com \
    username=trader \
    password=secure_password_here
"

# API keys for multiple services
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv put secret/sureshot-algo/apis \
    polygon_key=key1 \
    alpaca_key=key2 \
    alpaca_secret=secret1
"
```

**Verify secrets:**

```bash
# List all secrets
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv list secret/sureshot-algo
"

# Read specific secret
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv get secret/sureshot-algo/polygon
"

# Get just one field
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv get -field=api_key secret/sureshot-algo/polygon
"
```

---

## Verification

### Step 12: Test Application Access

Create a test pod to verify applications can authenticate and retrieve secrets:

```bash
# Create test pod with sureshot-algo ServiceAccount
cat <<EOF | microk8s kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: vault-test
  namespace: default
spec:
  serviceAccountName: sureshot-algo
  containers:
    - name: vault-client
      image: hashicorp/vault:1.15.2
      command: ["sleep", "3600"]
      env:
        - name: VAULT_ADDR
          value: "http://vault.vault.svc.cluster.local:8200"
EOF

# Wait for pod to be ready
microk8s kubectl wait --for=condition=ready pod/vault-test --timeout=60s
```

**Test authentication and secret retrieval:**

```bash
microk8s kubectl exec vault-test -- sh -c '
# Authenticate using Kubernetes method
VAULT_TOKEN=$(vault write -field=token auth/kubernetes/login \
  role=sureshot-algo \
  jwt=@/var/run/secrets/kubernetes.io/serviceaccount/token)

export VAULT_TOKEN

# Verify authentication
echo "✓ Successfully authenticated with Vault"

# Retrieve secret
echo ""
echo "Fetching Polygon API key..."
vault kv get -field=api_key secret/sureshot-algo/polygon
'
```

**What this tests:**

1. Pod can reach Vault service
2. Kubernetes authentication works
3. ServiceAccount has correct permissions
4. Policy allows reading secrets
5. Secret can be retrieved

**Expected output:**

```
✓ Successfully authenticated with Vault

Fetching Polygon API key...
YOUR_API_KEY_HERE
```

**Clean up test pod:**

```bash
microk8s kubectl delete pod vault-test
```

### Step 13: Test Persistence

Verify data survives pod restarts:

```bash
# Delete the Vault pod
microk8s kubectl delete pod -n vault vault-0

# Wait for automatic recreation
sleep 10
microk8s kubectl get pods -n vault

# Pod will be sealed - this is normal
microk8s kubectl exec -n vault vault-0 -- vault status

# Should show:
# Initialized: true   (data persisted!)
# Sealed: true        (needs unsealing)
```

**Unseal after restart:**

```bash
cd /home/user/Code_After_2025/projects/sureshot-algo-signals/k8s/vault

# Extract keys from backup
UNSEAL_KEY_1=$(jq -r '.unseal_keys_b64[0]' vault-keys.json)
UNSEAL_KEY_2=$(jq -r '.unseal_keys_b64[1]' vault-keys.json)
UNSEAL_KEY_3=$(jq -r '.unseal_keys_b64[2]' vault-keys.json)

# Unseal (need 3 keys)
microk8s kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_1
microk8s kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_2
microk8s kubectl exec -n vault vault-0 -- vault operator unseal $UNSEAL_KEY_3

# Verify unsealed
microk8s kubectl exec -n vault vault-0 -- vault status
```

**Verify secret still exists:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv get secret/sureshot-algo/polygon
"
```

**Why this test matters:**

- Confirms persistent storage is working
- Verifies unsealing process
- Ensures secrets survive pod restarts

---

## Troubleshooting

### Problem: Pod stuck in CrashLoopBackOff

**Check logs:**

```bash
microk8s kubectl logs -n vault vault-0 --tail=50
```

**Common causes:**

1. **"Failed to lock memory"**

   ```
   Error: Failed to lock memory: cannot allocate memory
   ```

   **Solution:** Add `disable_mlock = true` to ConfigMap (already done)

2. **Storage not mounted**

   ```
   Error: permission denied accessing /vault/data
   ```

   **Solution:** Check PVC is bound:

   ```bash
   microk8s kubectl get pvc -n vault
   # Should show: STATUS: Bound
   ```

3. **Configuration error**
   ```
   Error parsing config
   ```
   **Solution:** Check ConfigMap syntax:
   ```bash
   microk8s kubectl get configmap vault-config -n vault -o yaml
   ```

### Problem: Cannot initialize Vault

**Check status:**

```bash
microk8s kubectl exec -n vault vault-0 -- vault status
```

**If "Initialized: true" already:**

- Vault is already initialized
- Use existing unseal keys
- DO NOT re-initialize (will lose all data)

**If command fails:**

- Pod might not be ready yet
- Wait 30 seconds and try again

### Problem: Unseal keys don't work

**Verify you're using correct keys:**

```bash
# Check key format
jq '.unseal_keys_b64[0]' vault-keys.json

# Should be base64 string like: "Ab12Cd34..."
```

**If keys are lost:**

- **DATA IS PERMANENTLY LOST**
- Cannot recover without keys
- Must delete everything and start over:
  ```bash
  microk8s kubectl delete namespace vault
  microk8s kubectl delete pvc --all -n vault
  # Then redeploy from Step 1
  ```

### Problem: Pod can't authenticate

**Check ServiceAccount exists:**

```bash
microk8s kubectl get sa sureshot-algo -n default
```

**Check role configuration:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault read auth/kubernetes/role/sureshot-algo
"
```

**Verify bound names match:**

- ServiceAccount name in pod spec
- `bound_service_account_names` in role
- Namespace matches `bound_service_account_namespaces`

### Problem: Permission denied reading secret

**Check policy:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault policy read sureshot-algo-policy
"
```

**Verify path matches:**

- Policy: `secret/data/sureshot-algo/*`
- Secret path: `secret/sureshot-algo/polygon`
- Must be under the allowed path

**Check role has policy assigned:**

```bash
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault read auth/kubernetes/role/sureshot-algo
"

# Should show: policies = [sureshot-algo-policy]
```

---

## Complete Redeployment from Scratch

If you need to completely remove and redeploy:

```bash
# 1. Delete everything
microk8s kubectl delete namespace vault

# 2. Delete persistent volumes
microk8s kubectl get pv | grep vault
# Manually delete any remaining PVs

# 3. Wait for cleanup
sleep 30

# 4. Redeploy (follow all steps from beginning)
microk8s kubectl apply -f 00-namespace.yaml
microk8s kubectl apply -f 02-configmap.yaml
microk8s kubectl apply -f 03-statefulset.yaml
microk8s kubectl apply -f 04-service.yaml

# 5. Initialize (creates NEW keys)
./init-vault-microk8s.sh

# 6. Configure (Steps 7-10)
# 7. Add secrets (Step 11)
```

**WARNING:** This creates COMPLETELY NEW unseal keys. Previous keys will NOT work.

---

## Security Checklist

Before going to production:

- [ ] Unseal keys stored in 1Password (or secure location)
- [ ] Root token rotated (create admin user, revoke root)
- [ ] TLS enabled for Vault listener
- [ ] Audit logging enabled
- [ ] Backup strategy implemented
- [ ] Recovery procedures documented and tested
- [ ] Team trained on unsealing process
- [ ] Monitoring and alerting configured
- [ ] Network policies restricting Vault access
- [ ] Regular secret rotation scheduled

---

## Quick Reference

### Common Commands

```bash
# Check Vault status
microk8s kubectl exec -n vault vault-0 -- vault status

# List secrets
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv list secret/sureshot-algo
"

# Read secret
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv get secret/sureshot-algo/polygon
"

# Add secret
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv put secret/sureshot-algo/myapp \
    key1=value1 \
    key2=value2
"

# Delete secret
microk8s kubectl exec -n vault vault-0 -- sh -c "
export VAULT_TOKEN=$ROOT_TOKEN
vault kv delete secret/sureshot-algo/myapp
"

# Unseal after restart
jq -r '.unseal_keys_b64[0]' vault-keys.json | xargs -I {} microk8s kubectl exec -n vault vault-0 -- vault operator unseal {}
jq -r '.unseal_keys_b64[1]' vault-keys.json | xargs -I {} microk8s kubectl exec -n vault vault-0 -- vault operator unseal {}
jq -r '.unseal_keys_b64[2]' vault-keys.json | xargs -I {} microk8s kubectl exec -n vault vault-0 -- vault operator unseal {}
```

### File Locations

```
k8s/vault/
├── 00-namespace.yaml              # Namespace and RBAC
├── 02-configmap.yaml              # Vault configuration
├── 03-statefulset.yaml            # Vault deployment
├── 04-service.yaml                # Network services
├── init-vault-microk8s.sh         # Initialization script
└── vault-keys.json                # Unseal keys (SECURE THIS!)
```

---

## Support Resources

- [Vault Documentation](https://developer.hashicorp.com/vault/docs)
- [Kubernetes Auth Method](https://developer.hashicorp.com/vault/docs/auth/kubernetes)
- [KV Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/kv)
- [Vault Concepts](https://developer.hashicorp.com/vault/docs/concepts)

---

**Document Version:** 1.0
**Last Updated:** 2025-10-11
**Tested On:** microk8s v1.32
