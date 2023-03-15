terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 4.58.0"
      configuration_aliases = [aws.au]
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

// Provider for AU region
provider "aws" {
  alias  = "au"
  region = "ap-southeast-2"
}