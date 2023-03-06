terraform {
  backend "s3" {
    bucket = "aspiredu-terraform-states"
    region = "us-east-1"
  }
}


resource "aws_instance" "cb_backup" {
  ami             = local.ami // Ubuntu 22.04 AMI
  instance_type   = local.type
  key_name        = "aspire-pgbackups"
  security_groups = ["ssh-no-http"]

  tags = {
    Name = local.name_tag,
  }
  user_data = base64encode(templatefile("./bin/ec2_setup.sh", {
    CRUNCHY_TEAM_ID              = var.CRUNCHY_TEAM_ID
    CRUNCHY_API_KEY              = var.CRUNCHY_API_KEY
    ASPIRE_AWS_ACCESS_KEY_ID     = var.ASPIRE_AWS_ACCESS_KEY_ID
    ASPIRE_AWS_SECRET_ACCESS_KEY = var.ASPIRE_AWS_SECRET_ACCESS_KEY
    GIT_PAT                      = var.GIT_PAT
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

output "ASPIRE_BACKEND" {
  value       = var.ASPIRE_BACKEND
  description = "The backend the script is being run for."
}
