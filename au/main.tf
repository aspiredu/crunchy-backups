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
  ami = "ami-08f0bc76ca5236b20" // Ubuntu 22.04 AMI ap-southeast-2
}