#!/bin/bash
set -e

KUBECTL="microk8s kubectl"

echo "============================================"
echo "Vault Initialization Script (microk8s)"
echo "============================================"

# Wait for Vault pod to be running (not necessarily ready)
echo "Waiting for Vault pod to be running..."
$KUBECTL wait --for=jsonpath='{.status.phase}'=Running pod -l app=vault -n vault --timeout=300s || true

# Get the Vault pod name
VAULT_POD=$($KUBECTL get pods -n vault -l app=vault -o jsonpath='{.items[0].metadata.name}')
echo "Vault pod: $VAULT_POD"

# Check if Vault is already initialized
echo "Checking Vault status..."
INIT_STATUS=$($KUBECTL exec -n vault $VAULT_POD -- vault status -format=json 2>/dev/null | jq -r '.initialized' || echo "false")

if [ "$INIT_STATUS" = "true" ]; then
    echo "Vault is already initialized"
    echo "To unseal Vault, use the unseal keys from the initial setup"
    exit 0
fi

echo "Initializing Vault..."
# Initialize Vault with 5 key shares and 3 key threshold
INIT_OUTPUT=$($KUBECTL exec -n vault $VAULT_POD -- vault operator init -format=json -key-shares=5 -key-threshold=3)

# Save the output to a file (IMPORTANT: Store this securely!)
echo "$INIT_OUTPUT" > vault-keys.json
echo "Vault keys saved to vault-keys.json"
echo ""
echo "⚠️  IMPORTANT: Store vault-keys.json in a secure location!"
echo "⚠️  You will need these keys to unseal Vault after restarts"
echo ""

# Extract unseal keys and root token
UNSEAL_KEY_1=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[0]')
UNSEAL_KEY_2=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[1]')
UNSEAL_KEY_3=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[2]')
ROOT_TOKEN=$(echo "$INIT_OUTPUT" | jq -r '.root_token')

echo "Unsealing Vault..."
$KUBECTL exec -n vault $VAULT_POD -- vault operator unseal $UNSEAL_KEY_1
$KUBECTL exec -n vault $VAULT_POD -- vault operator unseal $UNSEAL_KEY_2
$KUBECTL exec -n vault $VAULT_POD -- vault operator unseal $UNSEAL_KEY_3

echo ""
echo "✅ Vault is now unsealed and ready to use"
echo ""
echo "Root Token: $ROOT_TOKEN"
echo ""
echo "To access Vault:"
echo "  $KUBECTL exec -n vault -it $VAULT_POD -- sh"
echo "  export VAULT_TOKEN=$ROOT_TOKEN"
echo ""
echo "Or port-forward to access the UI:"
echo "  $KUBECTL port-forward -n vault svc/vault 8200:8200"
echo "  Open http://localhost:8200 and login with the root token"
echo ""
