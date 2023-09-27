terraform {
  backend "s3" {
    bucket = "aspiredu-terraform-states"
    region = "us-east-1"
  }
}


module "crunchy_instance" {
  source = "../modules/crunchy_instance"
  providers = {
    aws = aws
  }
  ami                          = "ami-0557a15b87f6559cf" // Ubuntu 22.04 AMI US East
  key_name                     = "aspire-pgbackups"
  CRUNCHY_TEAM_ID              = var.CRUNCHY_TEAM_ID
  CRUNCHY_API_KEY              = var.CRUNCHY_API_KEY
  ASPIRE_AWS_ACCESS_KEY_ID     = var.ASPIRE_AWS_ACCESS_KEY_ID
  ASPIRE_AWS_SECRET_ACCESS_KEY = var.ASPIRE_AWS_SECRET_ACCESS_KEY
  GIT_PAT                      = var.GIT_PAT
  ASPIRE_CLUSTER               = var.ASPIRE_CLUSTER
  SENTRY_DSN                   = var.SENTRY_DSN
}
