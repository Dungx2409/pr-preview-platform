# Terraform Infrastructure (Phase 8 — Cloud Variant)

This directory contains Terraform Infrastructure as Code (IaC) implementing the PR Preview Platform's optional cloud variant (SPEC Phase 8). It targets AWS and is fully tested and verified against [LocalStack](https://localstack.cloud/) running locally on `http://localhost:4566`.

---

## 1. Architecture & Provisioned Resources

The IaC provisions a secure, isolated cloud environment intended to host the platform's k3s server node:

| Resource | Terraform Type | Purpose | Security Hardening |
|---|---|---|---|
| **VPC** | `aws_vpc.main` | Dedicated 10.0.0.0/16 network | Isolated network with DNS support enabled |
| **Public Subnet** | `aws_subnet.public` | 10.0.1.0/24 subnet | `map_public_ip_on_launch = false` |
| **Internet Gateway** | `aws_internet_gateway.main` | Outbound and ingress gateway | Attached directly to VPC |
| **Route Table** | `aws_route_table.public` | Default route (0.0.0.0/0 -> IGW) | Associated with the public subnet |
| **Security Group** | `aws_security_group.k3s_node` | Host firewall rules | **Port 22 (SSH) restricted to owner CIDR only**; **Port 6443 strictly DENIED**; full outbound egress |
| **EC2 Instance** | `aws_instance.k3s_node` | Single-node k3s server | Encrypted gp3 root EBS volume (30 GiB); non-root management |
| **Elastic IP** | `aws_eip.k3s_eip` | Static public IP for the VM | Domain = "vpc", associated via `aws_eip_association` |

### Security Design
- **No Kubernetes API Exposure:** Port 6443 is deliberately omitted from inbound rules. Cluster administration and preview access occur privately via the owner's Tailscale tailnet or through secure SSH tunneling (SPEC §6.5 & §9).
- **Owner-Only SSH:** Inbound port 22 is restricted to the specific owner CIDR configured via `allowed_ssh_cidr`.

---

## 2. Remote State & Locking

Remote state and concurrency locking are managed using AWS S3 and DynamoDB:
- **Backend:** `s3`
- **State Bucket:** `pr-preview-tfstate`
- **State Key:** `cloud-variant/terraform.tfstate`
- **Lock Table:** `pr-preview-tflocks` (DynamoDB table with partition key `LockID` of type `String`)
- **LocalStack Wiring:** `backend.tf` configures endpoints pointing to `http://localhost:4566` with path-style access enabled.

---

## 3. LocalStack Testing & Verification Guide

Follow these steps to initialize, deploy, verify, and destroy the infrastructure against LocalStack.

### Prerequisites
- LocalStack running at `http://localhost:4566` (e.g. via Docker / systemd)
- Terraform CLI (`~> 1.17`)
- AWS CLI v2

### Step 1: Set Dummy LocalStack Environment Variables
LocalStack accepts standard dummy credentials for local emulation:
```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_REGION=us-east-1
```

### Step 2: Create S3 State Bucket & DynamoDB Lock Table
Before initializing the remote backend, create the prerequisite resources in LocalStack:
```bash
# Create the S3 bucket for remote state
aws --endpoint-url=http://localhost:4566 s3 mb s3://pr-preview-tfstate

# Create DynamoDB table for state locking
aws --endpoint-url=http://localhost:4566 dynamodb create-table \
  --table-name pr-preview-tflocks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### Step 3: Initialize Terraform
```bash
cd infra/terraform
terraform init
```

### Step 4: Format and Validate
```bash
terraform fmt -check -recursive
terraform validate
```

### Step 5: Plan and Apply
Review execution plan and apply infrastructure changes:
```bash
# Plan
terraform plan

# Apply (auto-approved for automated CI/testing)
terraform apply -auto-approve
```

### Step 6: Verify Provisioned Resources via AWS CLI
Confirm that all 9 AWS resources exist in LocalStack:
```bash
# Verify VPC
aws --endpoint-url=http://localhost:4566 ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=cloud-variant-vpc"

# Verify Security Group (verify port 22 open, port 6443 absent)
aws --endpoint-url=http://localhost:4566 ec2 describe-security-groups \
  --filters "Name=group-name,Values=cloud-variant-k3s-node-sg"

# Verify EC2 Instance
aws --endpoint-url=http://localhost:4566 ec2 describe-instances \
  --filters "Name=tag:Name,Values=cloud-variant-k3s-node"

# Verify Elastic IP and Association
aws --endpoint-url=http://localhost:4566 ec2 describe-addresses
```

### Step 7: Teardown and Cleanup
Destroy all resources and verify clean state:
```bash
terraform destroy -auto-approve

# Confirm resources are gone
aws --endpoint-url=http://localhost:4566 ec2 describe-instances \
  --filters "Name=tag:Name,Values=cloud-variant-k3s-node"
```

### LocalStack Quirks & Behavior Notes
- **EC2 AMI Resolution (`DescribeImages`):** In LocalStack Pro, the EC2 service has an internal mock image catalog. When `root_block_device` is customized on an `aws_instance`, the Terraform AWS provider queries `DescribeImages` to read default root volume metadata. If an arbitrary AWS AMI (such as real Canonical AMIs) is passed without being registered in LocalStack, the provider returns `InvalidAMIID.NotFound: The image id does not exist`. To ensure smooth out-of-the-box local testing, `var.ami` defaults to `ami-785db401` (LocalStack's bundled Ubuntu image). For real AWS, supply the region's current Ubuntu 24.04 AMI via `terraform.tfvars`.
- **DynamoDB State Lock Deprecation Warning:** Terraform `>= 1.10` introduces S3 native state locking via `use_lockfile = true`, and emits a deprecation warning for `dynamodb_table`. However, DynamoDB state locking is retained here for full backward compatibility with standard AWS IaC patterns and LocalStack verification.

---

## 4. Production Deployment to Real AWS

To deploy against a real AWS account instead of LocalStack:
1. Copy `terraform.tfvars.example` to `terraform.tfvars` and configure real variables:
   - `allowed_ssh_cidr = "<YOUR_HOME_IP>/32"`
   - `ami = "<REAL_UBUNTU_AMI_FOR_YOUR_REGION>"`
   - `key_name = "<YOUR_AWS_KEY_PAIR_NAME>"`
2. In `backend.tf`: remove the `endpoints` block and LocalStack emulation flags, or configure an AWS S3 bucket and DynamoDB table created in your AWS account.
3. Configure your AWS credentials via `aws configure` or `AWS_PROFILE` (do NOT commit secrets or `.tfvars` to git).
4. Run standard `terraform init`, `terraform plan`, and `terraform apply`.
