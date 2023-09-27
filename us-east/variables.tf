variable "ami" {
  description = "The AMI for the image used for the EC2 instance."
  type        = string
  default     = ""
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

variable "ASPIRE_CLUSTER" {
  description = "The backend to run the script on."
  type        = string
  default     = ""
}

variable "SENTRY_DSN" {
  description = "The Sentry DSN token."
  type        = string
  default     = ""
}
