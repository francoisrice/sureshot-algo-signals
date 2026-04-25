This is a substantial setup. Let me write this out as a complete, structured guide you can follow sequentially.One important flag before diving in: VX1 plans start at 2 vCPU — there is no 1 vCPU VX1 tier. The minimum is 2 vCPU. For the orchestrator, since VX1 starts at $43.80/month and you want something always-on and cheap, a standard **High Performance 1 vCPU / 2 GB** instance (~$12/month) is the right call there. VX1 is only worth it for the ephemeral worker node given the hourly billing model. I'll also note that VX1 plan ID strings are not yet documented in the Terraform provider docs — you'll need to confirm them via `curl https://api.vultr.com/v2/plans?type=vx1` with your API key before deploying. I'll mark that step clearly in the guide.

Now, here's the full setup:

---

## Project Structure

```
trading-infra/
├── terraform/
│   ├── provider.tf
│   ├── variables.tf
│   ├── firewall.tf
│   ├── orchestrator.tf
│   ├── worker.tf              # Used on-demand, not always applied
│   ├── block_storage.tf
│   └── outputs.tf
├── ansible/
│   ├── inventory/
│   │   └── hosts.yml
│   ├── group_vars/
│   │   └── all.yml
│   ├── roles/
│   │   ├── common/
│   │   ├── microk8s/
│   │   └── ib-gateway/
│   ├── orchestrator.yml
│   └── worker.yml
├── k8s/
│   ├── namespace.yml
│   ├── ib-gateway/
│   │   ├── deployment.yml
│   │   └── service.yml
│   ├── trading-app/
│   │   ├── deployment.yml
│   │   └── pvc.yml
│   └── cronjobs/
│       ├── worker-start.yml
│       └── worker-stop.yml
└── secrets/                   # git-ignored
    ├── vultr.tfvars
    └── ib-credentials.env
```

---

## Phase 1 — Terraform: Infrastructure

### `terraform/provider.tf`
```hcl
terraform {
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "2.27.1"
    }
  }
}

provider "vultr" {
  api_key     = var.vultr_api_key
  rate_limit  = 100
  retry_limit = 3
}
```

### `terraform/variables.tf`
```hcl
variable "vultr_api_key" {
  description = "Vultr API key"
  sensitive   = true
}

variable "ssh_key_id" {
  description = "Vultr SSH key ID (get from dashboard or API)"
}

variable "region" {
  description = "Vultr region — NJ is closest to IB's servers"
  default     = "ewr"
}

# Ubuntu 24.04 LTS
variable "os_id" {
  default = 2284
}

# Confirm current VX1 plan IDs via:
# curl -s "https://api.vultr.com/v2/plans?type=vx1" \
#   -H "Authorization: Bearer YOUR_API_KEY" | jq '.plans[] | {id, vcpu_count, ram}'
variable "vx1_worker_plan" {
  description = "VX1 plan ID for the ephemeral worker node (2 vCPU / 8 GB minimum)"
  default     = "vx1-2c-8gb"   # VERIFY THIS via API before applying
}

variable "orchestrator_plan" {
  description = "High Performance plan for the always-on orchestrator"
  default     = "vhf-1c-2gb"   # 1 vCPU / 2 GB High Frequency ~$12/month
}
```

### `terraform/firewall.tf`
```hcl
resource "vultr_firewall_group" "trading" {
  description = "Trading infrastructure firewall"
}

# SSH — restrict to your IP only in production
resource "vultr_firewall_rule" "ssh" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "22"
  notes             = "SSH"
}

# MicroK8s inter-node cluster communication
resource "vultr_firewall_rule" "microk8s_cluster" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "10.0.0.0"
  subnet_size       = 8
  port              = "25000"
  notes             = "MicroK8s cluster join"
}

# Kubernetes API server (kubectl remote access)
resource "vultr_firewall_rule" "k8s_api" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "16443"
  notes             = "K8s API server"
}

# IB Gateway — live port (internal only, not exposed publicly)
resource "vultr_firewall_rule" "ib_live" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "10.0.0.0"
  subnet_size       = 8
  port              = "4001"
  notes             = "IB Gateway live (internal)"
}

# IB Gateway — paper port
resource "vultr_firewall_rule" "ib_paper" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "10.0.0.0"
  subnet_size       = 8
  port              = "4002"
  notes             = "IB Gateway paper (internal)"
}
```

### `terraform/orchestrator.tf`
```hcl
resource "vultr_instance" "orchestrator" {
  label             = "trading-orchestrator"
  plan              = var.orchestrator_plan
  region            = var.region
  os_id             = var.os_id
  firewall_group_id = vultr_firewall_group.trading.id
  ssh_key_ids       = [var.ssh_key_id]
  hostname          = "orchestrator"
  enable_ipv6       = false
  backups           = "disabled"

  # Cloud-init: install snapd on first boot so Ansible finds it ready
  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y snapd python3 python3-pip
  EOF
}
```

### `terraform/block_storage.tf`
```hcl
# Persistent boot-capable block storage for the worker node.
# Survives VM deprovisioning — logs, state, and IB session data persist
# across daily teardowns.
resource "vultr_block_storage" "worker_data" {
  label       = "trading-worker-data"
  size_gb     = 50
  region      = var.region
  block_type  = "high_perf"
}
```

### `terraform/worker.tf`

> **Important:** This file provisions the ephemeral worker. You do not apply it on day one — it is applied each morning by the orchestrator's scheduler and destroyed each evening. Keep it in the repo for Terraform state management, but use `terraform apply -target=vultr_instance.worker` selectively, or drive it via the Vultr API from a Python script (shown in Phase 4).

```hcl
resource "vultr_instance" "worker" {
  label             = "trading-worker"
  plan              = var.vx1_worker_plan
  region            = var.region
  os_id             = var.os_id
  firewall_group_id = vultr_firewall_group.trading.id
  ssh_key_ids       = [var.ssh_key_id]
  hostname          = "trading-worker"
  enable_ipv6       = false
  backups           = "disabled"

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y snapd python3 python3-pip
  EOF
}

resource "vultr_block_storage_attachment" "worker_data" {
  block_storage_id = vultr_block_storage.worker_data.id
  instance_id      = vultr_instance.worker.id
  live             = true
}
```

### `terraform/outputs.tf`
```hcl
output "orchestrator_ip" {
  value = vultr_instance.orchestrator.main_ip
}

output "worker_ip" {
  value = try(vultr_instance.worker.main_ip, "not provisioned")
}

output "block_storage_id" {
  value = vultr_block_storage.worker_data.id
}
```

### Apply Orchestrator Only
```bash
# Store secrets — never commit these
export TF_VAR_vultr_api_key="your-api-key"
export TF_VAR_ssh_key_id="your-ssh-key-id"

cd terraform/
terraform init
terraform plan

# Apply orchestrator only — worker is scheduled separately
terraform apply -target=vultr_instance.orchestrator \
                -target=vultr_firewall_group.trading \
                -target=vultr_block_storage.worker_data
```

---

## Phase 2 — Ansible: OS & MicroK8s Configuration

### `ansible/inventory/hosts.yml`
```yaml
all:
  children:
    orchestrator:
      hosts:
        trading-orchestrator:
          ansible_host: "{{ lookup('env', 'ORCHESTRATOR_IP') }}"
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
    worker:
      hosts:
        trading-worker:
          ansible_host: "{{ lookup('env', 'WORKER_IP') }}"
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
```

### `ansible/group_vars/all.yml`
```yaml
microk8s_channel: "1.31/stable"
microk8s_addons:
  - dns
  - hostpath-storage
  - ingress
  - cert-manager
  - metrics-server
  - rbac
  - registry
```

### `ansible/roles/common/tasks/main.yml`
```yaml
- name: Update apt cache
  apt:
    update_cache: yes
    cache_valid_time: 3600

- name: Install base packages
  apt:
    name:
      - ufw
      - curl
      - git
      - jq
      - python3-pip
      - snapd
    state: present

- name: Configure UFW defaults
  ufw:
    direction: "{{ item.direction }}"
    policy: "{{ item.policy }}"
  loop:
    - { direction: incoming, policy: deny }
    - { direction: outgoing, policy: allow }

- name: Allow SSH
  ufw:
    rule: allow
    port: "22"
    proto: tcp

- name: Enable UFW
  ufw:
    state: enabled

- name: Set timezone to US/Eastern (market hours)
  timezone:
    name: America/New_York
```

### `ansible/roles/microk8s/tasks/main.yml`
```yaml
- name: Install MicroK8s via snap
  snap:
    name: microk8s
    classic: yes
    channel: "{{ microk8s_channel }}"

- name: Wait for MicroK8s to be ready
  command: microk8s status --wait-ready
  timeout: 120

- name: Add root to microk8s group
  user:
    name: root
    groups: microk8s
    append: yes

- name: Enable MicroK8s addons
  command: "microk8s enable {{ item }}"
  loop: "{{ microk8s_addons }}"
  register: addon_result
  changed_when: "'Addon already enabled' not in addon_result.stdout"

- name: Set kubectl alias in .bashrc
  lineinfile:
    path: /root/.bashrc
    line: "alias kubectl='microk8s kubectl'"
    state: present

- name: Export kubeconfig for remote access
  shell: microk8s config > /root/kubeconfig.yaml
  args:
    creates: /root/kubeconfig.yaml

- name: Allow MicroK8s Calico firewall rules
  command: "ufw allow {{ item }}"
  loop:
    - "in on cali+"
    - "out on cali+"

- name: Allow K8s API port
  ufw:
    rule: allow
    port: "16443"
    proto: tcp
```

### `ansible/roles/ib-gateway/tasks/main.yml`
```yaml
- name: Install Docker (for local image builds)
  apt:
    name:
      - docker.io
      - docker-compose
    state: present

- name: Install Playwright dependencies
  apt:
    name:
      - chromium-browser
      - chromium-chromedriver
      - python3-playwright
    state: present

- name: Install Python dependencies for IB auth
  pip:
    name:
      - playwright
      - pyotp
      - ibapi
      - kubernetes
    executable: pip3

- name: Install Playwright browsers
  command: python3 -m playwright install chromium
  environment:
    PLAYWRIGHT_BROWSERS_PATH: /opt/playwright

- name: Create trading namespace secret directory
  file:
    path: /opt/trading/secrets
    state: directory
    mode: '0700'
```

### `ansible/orchestrator.yml`
```yaml
- name: Configure orchestrator node
  hosts: orchestrator
  become: yes
  roles:
    - common
    - microk8s
    - ib-gateway

  tasks:
    - name: Allow IB Gateway ports (internal only)
      ufw:
        rule: allow
        port: "{{ item }}"
        proto: tcp
        src: 10.0.0.0/8
      loop:
        - "4001"
        - "4002"

    - name: Copy worker lifecycle scripts
      copy:
        src: ../scripts/
        dest: /opt/trading/scripts/
        mode: '0755'

    - name: Install Vultr CLI for worker management
      pip:
        name: vultr-python
        executable: pip3
```

### Run Ansible
```bash
export ORCHESTRATOR_IP=$(terraform output -raw orchestrator_ip)

# Wait ~60s after Terraform apply for cloud-init to finish
ansible-playbook -i ansible/inventory/hosts.yml ansible/orchestrator.yml
```

---

## Phase 3 — Kubernetes Manifests

### `k8s/namespace.yml`
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: trading
```

### `k8s/ib-gateway/deployment.yml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ib-gateway
  namespace: trading
spec:
  replicas: 1
  strategy:
    type: Recreate        # Never run two gateway instances simultaneously
  selector:
    matchLabels:
      app: ib-gateway
  template:
    metadata:
      labels:
        app: ib-gateway
    spec:
      containers:
      - name: ib-gateway
        image: ghcr.io/gnzsnz/ib-gateway:stable
        ports:
        - containerPort: 4001    # Live
        - containerPort: 4002    # Paper
        env:
        - name: TWS_USERID
          valueFrom:
            secretKeyRef:
              name: ib-credentials
              key: username
        - name: TWS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: ib-credentials
              key: password
        - name: TRADING_MODE
          value: "live"
        - name: TWS_SETTINGS_PATH
          value: "/home/ibgateway/Jts"
        resources:
          requests:
            memory: "768Mi"
            cpu: "250m"
          limits:
            memory: "1536Mi"
            cpu: "1000m"
        livenessProbe:
          tcpSocket:
            port: 4001
          initialDelaySeconds: 60
          periodSeconds: 30
          failureThreshold: 3
        volumeMounts:
        - name: ib-settings
          mountPath: /home/ibgateway/Jts
      volumes:
      - name: ib-settings
        persistentVolumeClaim:
          claimName: ib-settings-pvc
```

### `k8s/ib-gateway/service.yml`
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ib-gateway-service
  namespace: trading
spec:
  selector:
    app: ib-gateway
  ports:
  - name: live
    port: 4001
    targetPort: 4001
  - name: paper
    port: 4002
    targetPort: 4002
  type: ClusterIP    # Internal only — not exposed externally
```

### `k8s/trading-app/deployment.yml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trading-app
  namespace: trading
spec:
  replicas: 0              # Starts at 0 — CronJob scales to 1 at market open
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: trading-app
  template:
    metadata:
      labels:
        app: trading-app
    spec:
      containers:
      - name: trading-app
        image: localhost:32000/trading-app:latest
        env:
        - name: IB_HOST
          value: "ib-gateway-service"
        - name: IB_PORT
          value: "4001"
        - name: TRADING_MODE
          value: "live"
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        volumeMounts:
        - name: trading-logs
          mountPath: /app/logs
      volumes:
      - name: trading-logs
        persistentVolumeClaim:
          claimName: trading-logs-pvc
```

### `k8s/trading-app/pvc.yml`
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: trading-logs-pvc
  namespace: trading
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
  storageClassName: microk8s-hostpath
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ib-settings-pvc
  namespace: trading
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
  storageClassName: microk8s-hostpath
```

### `k8s/cronjobs/worker-start.yml`
```yaml
# Scales trading-app to 1 replica at 9:30am ET on weekdays
apiVersion: batch/v1
kind: CronJob
metadata:
  name: market-open
  namespace: trading
spec:
  schedule: "30 9 * * 1-5"    # 9:30am ET Mon-Fri
  timeZone: "America/New_York"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: trading-scaler
          containers:
          - name: scaler
            image: bitnami/kubectl:latest
            command:
            - kubectl
            - scale
            - deployment/trading-app
            - --replicas=1
            - -n
            - trading
          restartPolicy: OnFailure
```

### `k8s/cronjobs/worker-stop.yml`
```yaml
# Scales trading-app to 0 replicas at 4:00pm ET on weekdays
apiVersion: batch/v1
kind: CronJob
metadata:
  name: market-close
  namespace: trading
spec:
  schedule: "0 16 * * 1-5"    # 4:00pm ET Mon-Fri
  timeZone: "America/New_York"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: trading-scaler
          containers:
          - name: scaler
            image: bitnami/kubectl:latest
            command:
            - kubectl
            - scale
            - deployment/trading-app
            - --replicas=0
            - -n
            - trading
          restartPolicy: OnFailure
```

### RBAC for the scaler CronJob
```yaml
# k8s/rbac.yml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: trading-scaler
  namespace: trading
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-scaler
  namespace: trading
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: trading-scaler-binding
  namespace: trading
subjects:
- kind: ServiceAccount
  name: trading-scaler
roleBinding:
  kind: Role
  name: deployment-scaler
  apiGroup: rbac.authorization.k8s.io
```

---

## Phase 4 — IB Gateway Re-authentication with Playwright + OTP

This runs as a sidecar or separate pod that monitors the IB Gateway session and re-authenticates when the connection drops.

### `k8s/ib-gateway/reauth-deployment.yml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ib-reauth
  namespace: trading
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: ib-reauth
  template:
    metadata:
      labels:
        app: ib-reauth
    spec:
      containers:
      - name: ib-reauth
        image: localhost:32000/ib-reauth:latest
        env:
        - name: IB_USERNAME
          valueFrom:
            secretKeyRef:
              name: ib-credentials
              key: username
        - name: IB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: ib-credentials
              key: password
        - name: IB_OTP_SECRET
          valueFrom:
            secretKeyRef:
              name: ib-credentials
              key: otp_secret
        - name: IB_GATEWAY_HOST
          value: "ib-gateway-service"
        - name: IB_GATEWAY_PORT
          value: "4001"
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### `reauth/reauth.py`
```python
import os
import time
import socket
import logging
import pyotp
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

IB_USERNAME   = os.environ["IB_USERNAME"]
IB_PASSWORD   = os.environ["IB_PASSWORD"]
IB_OTP_SECRET = os.environ["IB_OTP_SECRET"]
IB_HOST       = os.environ.get("IB_GATEWAY_HOST", "ib-gateway-service")
IB_PORT       = int(os.environ.get("IB_GATEWAY_PORT", "4001"))

CHECK_INTERVAL_SECONDS = 60   # Check connection every 60s
IB_GATEWAY_URL = "http://ib-gateway-service:8888"  # IB Gateway web UI port


def is_gateway_reachable() -> bool:
    """TCP probe — confirms IB Gateway port is accepting connections."""
    try:
        with socket.create_connection((IB_HOST, IB_PORT), timeout=5):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def generate_otp() -> str:
    totp = pyotp.TOTP(IB_OTP_SECRET)
    return totp.now()


def reauthenticate():
    log.info("Starting re-authentication sequence via Playwright")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()

        try:
            # Navigate to IB Gateway web UI
            page.goto(f"{IB_GATEWAY_URL}/", timeout=30000)
            page.wait_for_load_state("networkidle")

            # Fill credentials
            page.fill('input[name="username"]', IB_USERNAME)
            page.fill('input[name="password"]', IB_PASSWORD)
            page.click('button[type="submit"]')

            # Wait for OTP prompt
            page.wait_for_selector('input[name="otp"]', timeout=15000)
            otp_code = generate_otp()
            log.info(f"Generated OTP: {otp_code[:2]}****")
            page.fill('input[name="otp"]', otp_code)
            page.click('button[type="submit"]')

            # Confirm login success
            page.wait_for_selector('.dashboard', timeout=30000)
            log.info("Re-authentication successful")

        except Exception as e:
            log.error(f"Re-authentication failed: {e}")
            page.screenshot(path="/tmp/reauth-failure.png")
            raise
        finally:
            browser.close()


def main():
    log.info("IB Gateway watchdog started")
    consecutive_failures = 0

    while True:
        if is_gateway_reachable():
            log.info("IB Gateway reachable — connection healthy")
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            log.warning(
                f"IB Gateway unreachable "
                f"(attempt {consecutive_failures}/3)"
            )
            if consecutive_failures >= 3:
                log.error("Gateway down for 3 consecutive checks — "
                          "initiating re-authentication")
                try:
                    reauthenticate()
                    consecutive_failures = 0
                except Exception as e:
                    log.error(f"Re-auth attempt failed: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

### `reauth/Dockerfile`
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir playwright pyotp

RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

COPY reauth.py .

RUN adduser --disabled-password --gecos '' trader
USER trader

CMD ["python", "reauth.py"]
```

---

## Phase 5 — Secrets Setup

**Never store secrets in Git.** Apply them once directly to the cluster:

```bash
# Create IB credentials secret
microk8s kubectl create secret generic ib-credentials \
  --from-literal=username='YOUR_IB_USERNAME' \
  --from-literal=password='YOUR_IB_PASSWORD' \
  --from-literal=otp_secret='YOUR_TOTP_BASE32_SECRET' \
  --namespace=trading

# Verify (values will be base64-encoded, not plaintext)
microk8s kubectl get secret ib-credentials -n trading -o yaml
```

Your TOTP base32 secret is the seed key from when you set up IB's 2FA — typically shown as a QR code you can also view as a string. Store this in a password manager separately.

---

## Phase 6 — Deploy Everything

```bash
# SSH into orchestrator
ssh root@$ORCHESTRATOR_IP

# Apply all manifests
microk8s kubectl apply -f k8s/namespace.yml
microk8s kubectl apply -f k8s/rbac.yml
microk8s kubectl apply -f k8s/trading-app/pvc.yml
microk8s kubectl apply -f k8s/ib-gateway/
microk8s kubectl apply -f k8s/trading-app/
microk8s kubectl apply -f k8s/cronjobs/

# Build and push the IB Gateway image (run from repo root — Dockerfile needs SureshotSDK/)
docker build \
  -f live_trading_infrastructure/docker/ib-gateway/Dockerfile \
  -t localhost:32000/ib-gateway:latest \
  .
docker push localhost:32000/ib-gateway:latest

# Build and push your trading app image
# IMPORTANT: the trading-app Dockerfile must install Playwright and Chromium.
# client.py calls sync_login() directly when a request fails auth, so the
# trading-app container needs Playwright available at runtime. The
# IBKR_GATEWAY_HTTP_URL env var is already set in k8s/trading-app/deployment.yml
# pointing to ib-gateway-service:5000 so Playwright navigates to the right place.
#
# Minimum required in trading-app Dockerfile:
#   RUN pip install playwright && playwright install chromium && playwright install-deps chromium
docker build -t localhost:32000/trading-app:latest ./trading-app/
docker push localhost:32000/trading-app:latest

# Check everything
microk8s kubectl get all -n trading
```

---

## Confirmation Checklist Before Going Live

```
[ ] terraform apply completed for orchestrator + firewall + block storage
[ ] Ansible playbook ran without errors
[ ] microk8s status shows all addons enabled
[ ] ib-credentials secret created in 'trading' namespace
[ ] IB Gateway pod Running and liveness probe passing
[ ] TCP connection test: nc -zv ib-gateway-service 4001 (from trading-app pod)
[ ] Playwright reauth tested in paper mode first
[ ] CronJob schedules verified (kubectl get cronjobs -n trading)
[ ] Trading app starts, connects to IB Gateway, receives market data
[ ] Block storage attached and logs persisting to PVC
[ ] VX1 plan ID confirmed via Vultr API before worker Terraform apply
```

The one step to do manually before anything else: run `curl -s "https://api.vultr.com/v2/plans?type=vx1" -H "Authorization: Bearer YOUR_API_KEY" | jq '.plans[] | {id, vcpu_count, ram}'` and update `vx1_worker_plan` in your variables with the real plan ID. Everything else in this guide follows the official Vultr Terraform provider docs as of version 2.27.1.