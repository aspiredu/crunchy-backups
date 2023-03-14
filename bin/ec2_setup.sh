#!/bin/bash
sudo apt update
sudo apt install -y unzip python3-pip jq
while ! ls /dev/nvme1n1 > /dev/null
do 
    sleep 5s
done
echo "Creating XFS Filesystem on Attached Volume"
sudo mkfs -t xfs /dev/nvme1n1
sudo mkdir /home/ubuntu/data/
echo "Mounting Attached Volume"
sudo mount /dev/nvme1n1 /home/ubuntu/data/
echo "Creating new directories"
sudo mkdir /home/ubuntu/data/CrunchyBackupsData/
sudo chmod 777 /home/ubuntu/data/CrunchyBackupsData/
cd /home/ubuntu/data/CrunchyBackupsData/
sudo mkdir ${ASPIRE_BACKEND}
sudo chmod 777 ./*
cd /home/ubuntu/
echo "Cloning GitHub repository"
git clone https://github.com/aspiredu/crunchy-backups.git
echo "Installing AWS CLI"
sudo mkdir installations
cd installations
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
echo "Installing script dependencies"
cd /home/ubuntu/crunchy-backups/
pip3 install -r requirements.txt
pip3 install python-dotenv
tee ./bin/.env <<EOF
CRUNCHY_API_KEY = "${CRUNCHY_API_KEY}"
CRUNCHY_TEAM_ID = "${CRUNCHY_TEAM_ID}"

ASPIRE_AWS_ACCESS_KEY_ID = "${ASPIRE_AWS_ACCESS_KEY_ID}"
ASPIRE_AWS_SECRET_ACCESS_KEY = "${ASPIRE_AWS_SECRET_ACCESS_KEY}"
ASPIRE_BACKEND = "${ASPIRE_BACKEND}"

LOCAL_TEMP_DOWNLOADS_PATH = "/home/ubuntu/data/CrunchyBackupsData/"
BASE_S3_PREFIX = "crunchybridge/"
EOF
echo "Running script..."
python3 ./bin/crunchy_copy.py --backend ${ASPIRE_BACKEND}
echo "Sending request to begin infrastructure tear down..."
curl \
-X POST \
-H "Accept: application/vnd.github.v3+json" \
-H "Authorization: Bearer ${GIT_PAT}" \
https://api.github.com/repos/aspiredu/crunchy-backups/dispatches \
-d '{"event_type": "destroy", "client_payload": {"success": true, "backend": "${ASPIRE_BACKEND}"}}'
