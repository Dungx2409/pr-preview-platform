terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Compatibility flags for LocalStack emulation and AWS compatibility
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  default_tags {
    tags = merge(
      var.project_tags,
      {
        Environment = var.environment
        ManagedBy   = "terraform"
      }
    )
  }
}
