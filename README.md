A Python script used to transfer backups stored on the CrunchyBridge S3 Bucket to AspirEDU's S3 Bucket.


## Contributing

Install pre-commit hooks:

```bash
pre-commit install
```

Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Updating Python dependencies

```bash
source venv/bin/activate
pip-compile --upgrade
```

## Testing Locally

1. Ensure the Terraform CLI is installed. The following command should output the currently installed version of the Terraform CLI:

```
terraform --version
```

2. Open a new terminal and export the following variables:

```
export TF_VAR_CRUNCHY_TEAM_ID=CRUNCHY_TEAM_ID
export TF_VAR_CRUNCHY_API_KEY=CRUNCHY_API_KEY
export TF_VAR_ASPIRE_AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY
export TF_VAR_ASPIRE_AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_KEY
export TF_VAR_GIT_PAT=GIT_PERSONAL_ACCESS_TOKEN
export TF_VAR_ASPIRE_BACKEND=ASPIRE_BACKEND_TO_RUN_FOR
export AWS_ACCESS_KEY_ID=TERRAFORM_AWS_ACCESS_KEY
export AWS_SECRET_ACCESS_KEY=TERRAFORM_AWS_SECRET_KEY
```

3. Navigate to the directory in this repository for the region to use for testing (likely `us-east`).

4. Initialize Terraform with the following command, replacing `{ ASPIRE_BACKEND }` with the name of the backend being used for testing (this should match the `TF_VAR_ASPIRE_BACKEND` variable set above):

```
terraform init -backend-config="key={ ASPIRE_BACKEND }/terraform.tfstate"
```
e.g.
```
terraform init -backend-config="key=aspirestaging/terraform.tfstate"
```

5. (Optional but recommended) Verify the actions Terraform will take when applied with the following command:

```
terraform plan
```

6. Run the following command to apply the changes from Step 5 and provision the specified resources from AWS:

```
terraform apply
```

7. The EC2 Instance will be provisioned by Terraform along with the supporting Volume for storage. The state can be viewed through the AWS Web Portal. Connect to the EC2 Instance via SSH (instructions can be found on the AWS Web Portal).

Note: Accessing the instance via SSH requires the `.pem` private key file corresponding to the AWS Key Pair used by Terraform when provisioning the EC2 instance.

8. Verify the volume was mounted at the correct point in the file structure, verify the file structure itself is as expected, and check that the Python script is running. Here are a few useful commands:

View Attached Drives with Filesystem and Mount Points
```
lsblk -f
```

View Running Processes
```
htop
```

View Start-Up Script Sent to Userdata
```
curl http://169.254.169.254/latest/user-data
```

The logs for the Start-Up Script can be found at `/var/log/cloud-init-output.log`.

