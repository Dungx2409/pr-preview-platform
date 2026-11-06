variable "region" {
  type        = string
  description = "Target AWS region for deploying infrastructure resources."
  default     = "us-east-1"
}

variable "ami" {
  type        = string
  description = "AMI ID for the k3s server node instance (defaults to LocalStack Ubuntu AMI 'ami-785db401'; override with real AWS AMI in terraform.tfvars)."
  default     = "ami-785db401"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for the single-node k3s cluster (e.g., t3.medium)."
  default     = "t3.medium"
}

variable "key_name" {
  type        = string
  description = "SSH key pair name registered in AWS or LocalStack for node access."
  default     = "preview-platform-key"
}

variable "allowed_ssh_cidr" {
  type        = string
  description = "CIDR block permitted to connect via SSH (port 22). Strictly restricted to the owner IP; never 0.0.0.0/0 in production."
  default     = "192.168.1.0/24"
}

variable "project_tags" {
  type        = map(string)
  description = "Common resource tags applied across all managed AWS infrastructure."
  default = {
    Project = "pr-preview-platform"
  }
}

variable "environment" {
  type        = string
  description = "Environment identifier (e.g., cloud-variant, preview, production)."
  default     = "cloud-variant"
}
