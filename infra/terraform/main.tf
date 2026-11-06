# PR Preview Platform - Cloud Variant (Phase 8)
# Network, Security Group, EC2 Instance, and Elastic IP

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.environment}-vpc"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.environment}-public-subnet"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.environment}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.environment}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "k3s_node" {
  name        = "${var.environment}-k3s-node-sg"
  vpc_id      = aws_vpc.main.id
  description = "Security group for k3s single-node instance. Restricted SSH only; port 6443 is strictly denied."

  # Inbound rule: SSH port 22 strictly restricted to owner CIDR
  ingress {
    description = "SSH access restricted to owner IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  # IMPORTANT: Kubernetes API port 6443 is deliberately NOT exposed to the internet.
  # Cluster communication occurs securely via Tailscale tailnet or SSH tunnels.

  # Outbound: a k3s node must reach arbitrary internet hosts (apt mirrors, container
  # registries, Tailscale control plane) whose IPs are dynamic, so the egress CIDR is
  # 0.0.0.0/0. That is unavoidable for a node; pod-level egress is restricted separately
  # by the Kubernetes NetworkPolicy (SPEC §6.5). Hence the AVD-AWS-0104 ignore below.
  #trivy:ignore:AVD-AWS-0104
  egress {
    description = "Outbound for OS updates, container image pulls, Tailscale"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.environment}-k3s-sg"
  }
}

resource "aws_instance" "k3s_node" {
  ami                    = var.ami
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.k3s_node.id]
  key_name               = var.key_name

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    delete_on_termination = true
    encrypted             = true
  }

  tags = {
    Name = "${var.environment}-k3s-node"
    Role = "k3s-server"
  }
}

resource "aws_eip" "k3s_eip" {
  domain = "vpc"

  tags = {
    Name = "${var.environment}-eip"
  }
}

resource "aws_eip_association" "k3s_eip_assoc" {
  instance_id   = aws_instance.k3s_node.id
  allocation_id = aws_eip.k3s_eip.id
}
