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