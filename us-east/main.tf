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
  ami = "ami-0557a15b87f6559cf" // Ubuntu 22.04 AMI US East
}