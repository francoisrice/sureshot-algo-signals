Here is the full Sealed Secrets + Vault setup guide.

Sealed Secrets + Vault: Full Implementation Guide
Part 1 — Fix the Current Issue
You're on the orchestrator using plain kubectl instead of microk8s kubectl. Run all commands with microk8s kubectl on this node, or set the alias permanently:
bashecho "alias kubectl='microk8s kubectl'" >> ~/.bashrc
source ~/.bashrc
Then re-run the controller install:
bashmicrok8s kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.27.3/controller.yaml
Verify:
bashmicrok8s kubectl get pods -n kube-system | grep sealed-secrets
Expected output:
sealed-secrets-controller-xxxxxxxxx-xxxxx   1/1   Running   0   30s

Part 2 — Install kubeseal CLI
kubeseal is the client tool that encrypts secrets into SealedSecrets. Install it on the orchestrator:
bashwget https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.27.3/kubeseal-0.27.3-linux-amd64.tar.gz
tar -xvzf kubeseal-0.27.3-linux-amd64.tar.gz
install -m 755 kubeseal /usr/local/bin/kubeseal
Verify:
bashkubeseal --version

Part 3 — Install Vault
3.1 — Add the Vault Helm chart
bashmicrok8s enable helm3

microk8s helm3 repo add hashicorp https://helm.releases.hashicorp.com
microk8s helm3 repo update
3.2 — Create Vault namespace
bashmicrok8s kubectl create namespace vault
3.3 — Create Vault Helm values file
bashcat <<EOF > /opt/trading/vault-values.yaml
server:
  standalone:
    enabled: true
    config: |
      ui = true

      listener "tcp" {
        tls_disable = 1
        address = "[::]:8200"
        cluster_address = "[::]:8201"
      }

      storage "file" {
        path = "/vault/data"
      }

  dataStorage:
    enabled: true
    size: 10Gi
    storageClass: microk8s-hostpath

  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "500m"

  affinity: ""

ui:
  enabled: true
  serviceType: ClusterIP

injector:
  enabled: true
EOF
3.4 — Install Vault
bashmicrok8s helm3 install vault hashicorp/vault \
  --namespace vault \
  --values /opt/trading/vault-values.yaml
3.5 — Verify Vault pod is running
bashmicrok8s kubectl get pods -n vault
Expected output (Vault will show 0/1 Running initially — this is normal, it starts sealed):
vault-0                                  0/1   Running   0   60s
vault-agent-injector-xxxxxxxxx-xxxxx     1/1   Running   0   60s

Part 4 — Initialize Vault
4.1 — Initialize with a single unseal key
For your single-operator setup, 1 key share with a threshold of 1 is appropriate:
bashmicrok8s kubectl exec -n vault vault-0 -- \
  vault operator init \
  -key-shares=1 \
  -key-threshold=1 \
  -format=json > /opt/trading/vault-init.json
4.2 — Verify the output file
bashcat /opt/trading/vault-init.json
You will see something like:
json{
  "unseal_keys_b64": ["XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"],
  "unseal_keys_hex": ["XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"],
  "unseal_shares": 1,
  "unseal_threshold": 1,
  "recovery_keys_b64": [],
  "recovery_keys_hex": [],
  "recovery_keys_shares": 0,
  "recovery_keys_threshold": 0,
  "root_token": "hvs.XXXXXXXXXXXXXXXXXXXXXXXXX"
}
Save the root token and unseal key somewhere safe outside the server — a password manager, printed paper, anywhere offline. If you lose these, you lose access to Vault permanently.
4.3 — Unseal Vault manually (first time only)
bashUNSEAL_KEY=$(cat /opt/trading/vault-init.json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['unseal_keys_b64'][0])")

microk8s kubectl exec -n vault vault-0 -- \
  vault operator unseal $UNSEAL_KEY
4.4 — Verify Vault is unsealed
bashmicrok8s kubectl exec -n vault vault-0 -- vault status
You should see Sealed: false.

Part 5 — Create the Sealed Secret for the Unseal Key
This is the automation piece. The unseal key gets stored as a SealedSecret so the init container can read it on restart without human intervention.
5.1 — Create the raw K8s secret manifest (not applied to cluster)
bashUNSEAL_KEY=$(cat /opt/trading/vault-init.json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['unseal_keys_b64'][0])")

microk8s kubectl create secret generic vault-unseal-key \
  --namespace vault \
  --from-literal=unseal-key=$UNSEAL_KEY \
  --dry-run=client \
  -o yaml > /tmp/vault-unseal-key.yaml
5.2 — Encrypt it with kubeseal
bashkubeseal \
  --controller-name=sealed-secrets-controller \
  --controller-namespace=kube-system \
  --format yaml \
  < /tmp/vault-unseal-key.yaml \
  > /opt/trading/vault-unseal-key-sealed.yaml
5.3 — Apply the SealedSecret to the cluster
bashmicrok8s kubectl apply -f /opt/trading/vault-unseal-key-sealed.yaml
5.4 — Verify the secret was created
bashmicrok8s kubectl get secret vault-unseal-key -n vault
5.5 — Delete the plaintext files
bashrm /tmp/vault-unseal-key.yaml
# Keep vault-init.json only if you have no other backup of the root token
# If you've saved root token elsewhere, delete it:
rm /opt/trading/vault-init.json

Part 6 — Automate Unseal on Restart
This adds an init container to the Vault pod that reads the SealedSecret and unseals Vault automatically on every restart.
6.1 — Create the unseal script ConfigMap
bashcat <<'EOF' | microk8s kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: vault-unseal-script
  namespace: vault
data:
  unseal.sh: |
    #!/bin/sh
    set -e

    VAULT_ADDR="http://127.0.0.1:8200"
    MAX_RETRIES=30
    RETRY_INTERVAL=5

    echo "Waiting for Vault to start..."
    i=0
    until curl -sf $VAULT_ADDR/v1/sys/health > /dev/null 2>&1 || [ $i -eq $MAX_RETRIES ]; do
      i=$((i+1))
      echo "Attempt $i/$MAX_RETRIES..."
      sleep $RETRY_INTERVAL
    done

    SEALED=$(curl -sf $VAULT_ADDR/v1/sys/health | python3 -c \
      "import sys,json; print(json.load(sys.stdin).get('sealed', True))")

    if [ "$SEALED" = "True" ]; then
      echo "Vault is sealed — unsealing..."
      curl -sf \
        --request PUT \
        --data "{\"key\": \"$UNSEAL_KEY\"}" \
        $VAULT_ADDR/v1/sys/unseal
      echo "Vault unsealed successfully"
    else
      echo "Vault already unsealed — nothing to do"
    fi
EOF
6.2 — Create RBAC so the init container can read the secret
bashcat <<EOF | microk8s kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vault-unseal
  namespace: vault
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vault-unseal-role
  namespace: vault
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["vault-unseal-key"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: vault-unseal-binding
  namespace: vault
subjects:
- kind: ServiceAccount
  name: vault-unseal
  namespace: vault
roleRef:
  kind: Role
  name: vault-unseal-role
  apiGroup: rbac.authorization.k8s.io
EOF
6.3 — Patch the Vault Helm values to add the init container
Update /opt/trading/vault-values.yaml — replace the file contents with:
yamlserver:
  standalone:
    enabled: true
    config: |
      ui = true

      listener "tcp" {
        tls_disable = 1
        address = "[::]:8200"
        cluster_address = "[::]:8201"
      }

      storage "file" {
        path = "/vault/data"
      }

  dataStorage:
    enabled: true
    size: 10Gi
    storageClass: microk8s-hostpath

  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "500m"

  affinity: ""

  serviceAccount:
    create: false
    name: vault-unseal

  extraInitContainers:
    - name: unseal
      image: python3:3.11-slim
      command: ["/bin/sh", "/scripts/unseal.sh"]
      env:
        - name: UNSEAL_KEY
          valueFrom:
            secretKeyRef:
              name: vault-unseal-key
              key: unseal-key
      volumeMounts:
        - name: unseal-script
          mountPath: /scripts

  extraVolumes:
    - name: unseal-script
      configMap:
        name: vault-unseal-script
        defaultMode: 0755

ui:
  enabled: true
  serviceType: ClusterIP

injector:
  enabled: true
6.4 — Apply the updated Helm values
bashmicrok8s helm3 upgrade vault hashicorp/vault \
  --namespace vault \
  --values /opt/trading/vault-values.yaml

Part 7 — Configure Vault for the Trading Namespace
7.1 — Set environment variables for Vault CLI
bashexport VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=$(cat /opt/trading/vault-init.json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['root_token'])")

# Port-forward Vault so you can reach it from the orchestrator shell
microk8s kubectl port-forward -n vault vault-0 8200:8200 &
7.2 — Enable the KV secrets engine
bashvault secrets enable -path=trading kv-v2
7.3 — Store IB credentials
bashvault kv put trading/ib-credentials \
  username="YOUR_IB_USERNAME" \
  password="YOUR_IB_PASSWORD" \
  otp_secret="YOUR_TOTP_BASE32_SECRET"
7.4 — Store the Vultr API key
bashvault kv put trading/vultr \
  api_key="YOUR_VULTR_API_KEY"
7.5 — Create a policy for the trading namespace
bashcat <<EOF | vault policy write trading-policy -
path "trading/*" {
  capabilities = ["read", "list"]
}
EOF
7.6 — Enable Kubernetes auth method
bashvault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://10.152.183.1:443" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
7.7 — Create a role for the trading namespace
bashvault write auth/kubernetes/role/trading \
  bound_service_account_names=trading-app \
  bound_service_account_namespaces=trading \
  policies=trading-policy \
  ttl=1h

Part 8 — Wire Vault into the Trading Pods
8.1 — Annotate your trading deployments to use Vault Agent injection
Add these annotations to your ib-gateway and trading-app deployment pod specs:
yaml# In the pod template metadata of each deployment
annotations:
  vault.hashicorp.com/agent-inject: "true"
  vault.hashicorp.com/role: "trading"
  vault.hashicorp.com/agent-inject-secret-ib-credentials: "trading/ib-credentials"
  vault.hashicorp.com/agent-inject-template-ib-credentials: |
    {{- with secret "trading/ib-credentials" -}}
    export IB_USERNAME="{{ .Data.data.username }}"
    export IB_PASSWORD="{{ .Data.data.password }}"
    export IB_OTP_SECRET="{{ .Data.data.otp_secret }}"
    {{- end }}
Vault Agent will inject the secrets as environment variables into the pod at runtime — they never touch disk and never appear in your K8s secret store.

Part 9 — Verify the Full Chain
bash# 1. Sealed Secrets controller running
microk8s kubectl get pods -n kube-system | grep sealed-secrets

# 2. Vault running and unsealed
microk8s kubectl exec -n vault vault-0 -- vault status

# 3. SealedSecret exists
microk8s kubectl get sealedsecret -n vault

# 4. Secret was created from SealedSecret
microk8s kubectl get secret vault-unseal-key -n vault

# 5. IB credentials readable from Vault
vault kv get trading/ib-credentials

# 6. Trading pods receiving injected secrets
microk8s kubectl exec -n trading \
  deployment/trading-app \
  -- env | grep IB_

Restart Simulation Test
Before going live, test the auto-unseal by restarting the Vault pod:
bashmicrok8s kubectl delete pod vault-0 -n vault

# Watch it come back and auto-unseal
microk8s kubectl get pods -n vault -w

# Confirm unsealed after restart
microk8s kubectl exec -n vault vault-0 -- vault status | grep Sealed
# Should show: Sealed false
If that returns Sealed false without any manual intervention, the full auto-unseal chain is working correctly and you're ready to move on to the trading pod deployment.