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

variable "vx1_worker_plan" {
  description = "VX1 plan ID for the ephemeral worker node (2 vCPU / 8 GB minimum)"
  default     = "vx1-g-2c-8g-120s"
}

variable "orchestrator_plan" {
  description = "High Performance plan for the always-on orchestrator"
  default     = "vc2-1c-2gb"   # 1 vCPU / 1 GB General Compute ~$5/month
}