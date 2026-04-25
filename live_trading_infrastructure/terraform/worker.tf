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

