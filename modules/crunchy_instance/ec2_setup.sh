#!/bin/bash
apt update
apt install -y unzip python3-pip jq

LOCAL_TEMP_DOWNLOADS_PATH="${HOME}/data/CrunchyBackupsData/"

while ! ls /dev/nvme1n1 > /dev/null
do
    echo "Waiting for attached volume to be available..."
    sleep 5s
done
echo "Creating XFS Filesystem on Attached Volume"
mkfs -t xfs /dev/nvme1n1

echo "Creating new directories"
mkdir -p "${LOCAL_TEMP_DOWNLOADS_PATH}${ASPIRE_BACKEND}"
chmod -R 760 ${LOCAL_TEMP_DOWNLOADS_PATH}

echo "Mounting Attached Volume"
mount /dev/nvme1n1 "${HOME}/data/"

echo "Installing AWS CLI"
mkdir "${HOME}/installations"
cd "${HOME}/installations"
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install

echo "Cloning GitHub repository"
cd $HOME
git clone https://github.com/aspiredu/crunchy-backups.git

echo "Installing script dependencies"
cd "${HOME}/crunchy-backups/"
pip3 install -r requirements.txt

echo "Creating .env file"
tee ./bin/.env <<EOF
CRUNCHY_API_KEY = "${CRUNCHY_API_KEY}"
CRUNCHY_TEAM_ID = "${CRUNCHY_TEAM_ID}"

ASPIRE_AWS_ACCESS_KEY_ID = "${ASPIRE_AWS_ACCESS_KEY_ID}"
ASPIRE_AWS_SECRET_ACCESS_KEY = "${ASPIRE_AWS_SECRET_ACCESS_KEY}"
ASPIRE_BACKEND = "${ASPIRE_BACKEND}"

LOCAL_TEMP_DOWNLOADS_PATH = "{LOCAL_TEMP_DOWNLOADS_PATH}"
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
