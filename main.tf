resource "aws_instance" "cb_backup" {
  ami             = local.ami // Ubuntu 22.04 AMI
  instance_type   = local.type
  key_name        = "aspire-pgbackups"
  security_groups = ["ssh-no-http"]

  tags = {
    Name = local.name_tag,
  }
  user_data = file("./bin/ec2_setup.sh")
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
