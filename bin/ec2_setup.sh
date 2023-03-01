
#!/bin/bash
sudo apt update
sudo apt install -y unzip python3-pip
while ! ls /dev/nvme1n1 > /dev/null
do 
    sleep 5
done
echo "Creating XFS Filesystem on Attached Volume"
sudo mkfs -t xfs /dev/nvme1n1
sudo mkdir /home/ubuntu/data/
echo "Mounting Attached Volume"
sudo mount /dev/nvme1n1 /home/ubuntu/data/
echo "Creating new directories"
sudo mkdir /home/ubuntu/data/CrunchyBackups/
cd /home/ubuntu/data/CrunchyBackups/
sudo mkdir aspiredu-au aspiredu-ms aspiredu-prd-a aspiredu-prd-b aspiredu-prd-c aspiredu-prd-d aspiredu-prd-e aspiredu-prd-g aspiredu-prd-h aspiredu-prd-i aspiredu-prd-j aspiredu-prd-k aspiredu-prd-l aspiredu-stg aspireprod aspirestaging
cd /home/ubuntu/
echo "Cloning GitHub repository"
git clone https://github.com/aspiredu/heroku-database-backups.git
echo "Installing AWS CLI"
sudo mkdir installations
cd installations
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
echo "Installing script dependencies"
cd /home/ubuntu/heroku-database-backups/
pip3 install -r requirements.txt
