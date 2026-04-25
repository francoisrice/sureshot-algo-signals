output "orchestrator_ip" {
  value = vultr_instance.orchestrator.main_ip
}

output "worker_ip" {
  value = try(vultr_instance.worker.main_ip, "not provisioned")
}