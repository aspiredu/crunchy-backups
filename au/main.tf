terraform {
  backend "s3" {
    bucket = "aspiredu-terraform-states"
    region = "us-east-1"
  }
}


module "crunchy_instance" {
  source = "../modules/crunchy_instance"
  providers = {
    aws = aws.au
  }
  ami                          = "ami-08f0bc76ca5236b20" // Ubuntu 22.04 AMI ap-southeast-2
  key_name                     = "aspire-pgbackups-au"
  CRUNCHY_TEAM_ID              = var.CRUNCHY_TEAM_ID
  CRUNCHY_API_KEY              = var.CRUNCHY_API_KEY
  ASPIRE_AWS_ACCESS_KEY_ID     = var.ASPIRE_AWS_ACCESS_KEY_ID
  ASPIRE_AWS_SECRET_ACCESS_KEY = var.ASPIRE_AWS_SECRET_ACCESS_KEY
  GIT_PAT                      = var.GIT_PAT
  ASPIRE_BACKEND               = var.ASPIRE_BACKEND
  SENTRY_DSN                   = var.SENTRY_DSN
}
