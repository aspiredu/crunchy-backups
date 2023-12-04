terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_instance" "cb_backup" {
  ami             = var.ami // Ubuntu 22.04 AMI
  instance_type   = local.type
  key_name        = var.key_name
  security_groups = ["ssh-no-http"]

  tags = {
    Name = "${var.ASPIRE_CLUSTER}-pgbackups",
  }
  user_data = base64encode(templatefile("${path.module}/ec2_setup.tftpl", {
    CRUNCHY_TEAM_ID              = var.CRUNCHY_TEAM_ID
    CRUNCHY_API_KEY              = var.CRUNCHY_API_KEY
    ASPIRE_AWS_ACCESS_KEY_ID     = var.ASPIRE_AWS_ACCESS_KEY_ID
    ASPIRE_AWS_SECRET_ACCESS_KEY = var.ASPIRE_AWS_SECRET_ACCESS_KEY
    GIT_PAT                      = var.GIT_PAT
    ASPIRE_CLUSTER               = var.ASPIRE_CLUSTER
    SENTRY_DSN                   = var.SENTRY_DSN
    BACKUP_TARGET                = var.BACKUP_TARGET
  }))
}

resource "aws_ebs_volume" "volume" {
  availability_zone = aws_instance.cb_backup.availability_zone
  size              = 2048
  type              = "gp2"
  tags = {
    Name = "aspire-pgbackups-volume"
  }
}

resource "aws_volume_attachment" "ec2_ebs_att" {
  device_name  = "/dev/sdd"
  volume_id    = aws_ebs_volume.volume.id
  instance_id  = aws_instance.cb_backup.id
  force_detach = true
}

output "ASPIRE_CLUSTER" {
  value       = var.ASPIRE_CLUSTER
  description = "The backend the script is being run for."
}
