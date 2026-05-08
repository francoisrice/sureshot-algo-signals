resource "vultr_firewall_group" "trading" {
  description = "Trading infrastructure firewall"
}

# SSH — restrict to your IP only in production - ie static IP
resource "vultr_firewall_rule" "ssh" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "22"
  notes             = "SSH"
}

# Calico VXLAN overlay — pods use UDP 4789 for cross-node traffic (no VPC, public IPs only)
resource "vultr_firewall_rule" "calico_vxlan" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "udp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "4789"
  notes             = "Calico VXLAN"
}

# MicroK8s cluster join — open to any IP since worker nodes join over public IPs (no VPC)
resource "vultr_firewall_rule" "microk8s_cluster" {
  firewall_group_id = vultr_firewall_group.trading.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
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