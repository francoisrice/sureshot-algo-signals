# Live Trading Architecture

## Tree

live-trading-infrastructure/
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
├── docker/
│   └── ib-gateway/
│       ├── Dockerfile         # Java 17 + Python + Playwright; build from repo root
│       └── start.sh           # Starts gateway JAR, waits, runs initial Playwright login
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

## Create infrastructure with Terraform

source live_trading_infrastructure/.env.sh                                                  
  cd live_trading_infrastructure/terraform                                                    
  terraform apply -target=vultr_firewall_group.trading \                                                    
    -target=vultr_firewall_rule.ssh \                                                         
    -target=vultr_firewall_rule.k8s_api \
    -target=vultr_firewall_rule.microk8s_cluster \                                            
    -target=vultr_firewall_rule.ib_live \                                                   
    -target=vultr_firewall_rule.ib_paper \                                                    
    -target=vultr_instance.orchestrator

## Provision Orchestrator node with Ansible

```bash
$ export ORCHESTRATOR_IP=$(terraform output -raw orchestrator_ip) # run this from /terraform
```

cd ../
ansible-playbook -i ansible/inventory/hosts.yml ansible/orchestrator.yml


## Build and push container images

The Dockerfile build context must be the **repo root** (not the docker/ subdirectory)
so the COPY instructions can reach SureshotSDK/.

```bash
# Set your registry — e.g. ghcr.io/your-org, docker.io/youruser, or localhost:32000
export REGISTRY=<YOUR_REGISTRY_TBD> # export REGISTRY=sureshotcapital

# IB Gateway (Java Client Portal Gateway + Playwright auth)
# Run from repo root
docker build \
  -f live_trading_infrastructure/docker/ib-gateway/Dockerfile \
  -t $REGISTRY/ib-gateway:latest \
  .
docker push $REGISTRY/ib-gateway:latest

# Trading app
# NOTE: the trading-app Dockerfile must include Playwright (playwright install chromium)
# because client.py calls sync_login() directly for re-auth on request failures.
# IBKR_GATEWAY_HTTP_URL is already set in k8s/trading-app/deployment.yml and points
# to ib-gateway-service:5000 so Playwright knows where to navigate.
docker build \
  -f live_trading_infrastructure/docker/trading-app/Dockerfile \
  -t $REGISTRY/trading-app:latest \
  .
docker push $REGISTRY/trading-app:latest
```

Once pushed, update the `image:` fields in:
- `k8s/ib-gateway/deployment.yml`
- `k8s/trading-app/deployment.yml`

to `$REGISTRY/ib-gateway:latest` and `$REGISTRY/trading-app:latest` respectively.

## Setup strategies on the orchestration node

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

# Check everything
microk8s kubectl get all -n trading
```
