#!/bin/bash
set -e

echo "============================================"
echo "Vault Configuration Script"
echo "============================================"

# Check if ROOT_TOKEN is provided
if [ -z "$ROOT_TOKEN" ]; then
    echo "Error: ROOT_TOKEN environment variable is required"
    echo "Usage: ROOT_TOKEN=<your-root-token> ./configure-vault.sh"
    exit 1
fi

# Get the Vault pod name
VAULT_POD=$(kubectl get pods -n vault -l app=vault -o jsonpath='{.items[0].metadata.name}')
echo "Vault pod: $VAULT_POD"

echo ""
echo "Step 1: Enabling KV secrets engine..."
kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault secrets enable -path=secret kv-v2 || echo 'KV engine may already be enabled'
"

echo ""
echo "Step 2: Creating Polygon API key secret..."
read -p "Enter your Polygon API key: " POLYGON_API_KEY

kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault kv put secret/sureshot-algo/polygon api_key=$POLYGON_API_KEY
"

echo ""
echo "Step 3: Enabling Kubernetes auth method..."
kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault auth enable kubernetes || echo 'Kubernetes auth may already be enabled'
"

echo ""
echo "Step 4: Configuring Kubernetes auth..."
# Get Kubernetes host
K8S_HOST=$(kubectl exec -n vault $VAULT_POD -- sh -c 'cat /var/run/secrets/kubernetes.io/serviceaccount/ca.crt | base64 -w 0' 2>/dev/null || kubectl exec -n vault $VAULT_POD -- sh -c 'cat /var/run/secrets/kubernetes.io/serviceaccount/ca.crt | base64')

kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault write auth/kubernetes/config \
        kubernetes_host=\"https://\$KUBERNETES_PORT_443_TCP_ADDR:443\"
"

echo ""
echo "Step 5: Creating policy for application access..."
kubectl exec -n vault $VAULT_POD -- sh -c "
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

echo ""
echo "Step 6: Creating Kubernetes auth role..."
kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault write auth/kubernetes/role/sureshot-algo \
        bound_service_account_names=sureshot-algo \
        bound_service_account_namespaces=default \
        policies=sureshot-algo-policy \
        ttl=24h
"

echo ""
echo "✅ Vault configuration complete!"
echo ""
echo "Summary of secrets stored:"
kubectl exec -n vault $VAULT_POD -- sh -c "
    export VAULT_TOKEN=$ROOT_TOKEN
    vault kv list secret/sureshot-algo
"

echo ""
echo "To verify the secret:"
echo "  kubectl exec -n vault -it $VAULT_POD -- sh"
echo "  export VAULT_TOKEN=$ROOT_TOKEN"
echo "  vault kv get secret/sureshot-algo/polygon"
echo ""
