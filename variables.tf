locals {
  ami             = "ami-0557a15b87f6559cf" // Ubuntu 22.04 AMI US East
  ami_au          = "ami-08f0bc76ca5236b20" // Ubuntu 22.04 AMI ap-southeast-2
  type            = "t3.xlarge"
  region          = "us-east-1"
  au_region       = "ap-southeast-2"
  volume_size     = 2048
  ebs_device_name = "/dev/nvme1n1"
}

variable "CRUNCHY_TEAM_ID" {
  description = "AspirEDU Team ID to authenticate with the Crunchy Bridge API."
  type        = string
  default     = ""
}
variable "CRUNCHY_API_KEY" {
  description = "API Key to authenticate with the Crunchy Bridge API."
  type        = string
  default     = ""
}

variable "ASPIRE_AWS_ACCESS_KEY_ID" {
  description = "Access Key ID to authenticate with AspirEDU's AWS resources."
  type        = string
  default     = ""
}

variable "ASPIRE_AWS_SECRET_ACCESS_KEY" {
  description = "Secret Access Key to authenticate with AspirEDU's AWS resources."
  type        = string
  default     = ""
}

variable "GIT_PAT" {
  description = "GitHub Personal Access Token to trigger tear down when script is done."
  type        = string
  default     = ""
}

variable "ASPIRE_BACKEND" {
  description = "The backend to run the script on."
  type        = string
  default     = ""
}
