terraform {
  backend "s3" {
    bucket         = "pr-preview-tfstate"
    key            = "cloud-variant/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "pr-preview-tflocks"

    # Endpoints configured for LocalStack emulation (port 4566)
    endpoints = {
      s3       = "http://localhost:4566"
      dynamodb = "http://localhost:4566"
    }

    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_path_style              = true
  }
}
