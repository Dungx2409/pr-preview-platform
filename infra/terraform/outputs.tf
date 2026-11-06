output "public_ip" {
  description = "Elastic IP address allocated to the k3s node (marked sensitive to prevent leaking public IP in CI/CD logs)."
  value       = aws_eip.k3s_eip.public_ip
  sensitive   = true
}

output "instance_id" {
  description = "EC2 instance ID of the k3s server node."
  value       = aws_instance.k3s_node.id
}

output "vpc_id" {
  description = "VPC ID of the PR Preview platform cloud variant network."
  value       = aws_vpc.main.id
}

output "subnet_id" {
  description = "Public subnet ID where the k3s instance is deployed."
  value       = aws_subnet.public.id
}
