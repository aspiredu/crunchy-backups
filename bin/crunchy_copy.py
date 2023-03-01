import boto3
import requests
import json
import subprocess
import os
import shutil
import argparse
from zoneinfo import ZoneInfo
from datetime import datetime

from dotenv import load_dotenv

# boto3.set_stream_logger(name='botocore')

# ENV Variables
load_dotenv()
CRUNCHY_API_KEY = os.getenv("CRUNCHY_API_KEY")
CRUNCHY_TEAM_ID = os.getenv("CRUNCHY_TEAM_ID")

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")

CLUSTERS_TO_BACKUP = os.getenv("CLUSTERS_TO_BACKUP").split(",")

LOCAL_TEMP_DOWNLOADS_PATH = os.getenv("LOCAL_TEMP_DOWNLOADS_PATH")
BASE_S3_PREFIX = os.getenv("BASE_S3_PREFIX")

# Parse Arguments
parser = argparse.ArgumentParser(
    prog="CrunchyBridge Backup",
    description="Moves backups from CrunchyBridge's S3 Buckets to "
    "AspirEDU's S3 Bucket",
)

parser.add_argument("-t", "--target")
parser.add_argument("-d", "--delete", action=argparse.BooleanOptionalAction)
args = parser.parse_args()


def get_crunchy_clusters():
    headers = {
        "Authorization": f"Bearer {CRUNCHY_API_KEY}",
    }
    response = requests.get(
        f"https://api.crunchybridge.com/clusters?team_id={CRUNCHY_TEAM_ID}",
        headers=headers,
    )
    return json.loads(response.content.decode("utf-8"))["clusters"]


def get_cluster_backup_info(cluster_id):
    headers = {
        "Authorization": f"Bearer {CRUNCHY_API_KEY}",
    }
    backup_tokens = requests.post(
        f"https://api.crunchybridge.com/clusters/{cluster_id}/backup-tokens",
        headers=headers,
    )
    backup_info = requests.get(
        f"https://api.crunchybridge.com/clusters/{cluster_id}/backups"
        "?order=desc&order_field=name",
        headers=headers,
    )
    response = json.loads(backup_tokens.content.decode("utf-8"))
    backup_info = json.loads(backup_info.content.decode("utf-8"))
    response["backups"] = backup_info["backups"]
    return response


def get_s3(access_key_id, secret_access_key, session_token=None):
    session = boto3.session.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token,
    )
    return session.resource("s3"), session.client("s3")


def watch_process_logs(process):
    while True:
        output = process.stdout.readline()
        print(output.strip())
        return_code = process.poll()
        if return_code is not None:
            if not return_code == 0:
                print("RETURN CODE", return_code)
            # Process has finished, read rest of the output
            for output in process.stdout.readlines():
                print(output.strip())
            return


def upload_all_files_in_dir(source_dir, stanza, bucket, backend_name, prefix=None):
    print("Uploading files...")
    if not source_dir.endswith("/"):
        source_dir = source_dir + "/"
    for root, _, files in os.walk(source_dir):
        for file in files:
            full_path = os.path.join(root, file)

            # Set up the file structure for S3
            new_file_key = f"{prefix}{backend_name}/{full_path[len(source_dir):]}"
            print(f"Uploading... {new_file_key}")
            bucket.upload_file(os.path.join(root, file), new_file_key)
    return


def delete_all_files_in_dir(source_dir):
    print("Cleaning up!!")
    if not source_dir.endswith("/"):
        source_dir = source_dir + "/"
    for filename in os.listdir(source_dir):
        file_path = os.path.join(source_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print("Failed to delete %s. Reason: %s" % (file_path, e))
    return


def backup_exists(s3, bucket, cluster_name, backup_name):
    if not backup_name.endswith("/"):
        backup_name = backup_name + "/"
    prefix = f"crunchybridge/{cluster_name}/backup/{backup_name}"
    resp = s3.list_objects(Bucket=bucket.name, Prefix=prefix, MaxKeys=1)
    return "Contents" in resp


def seconds_to_readable(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return h, m, s

def summarize(start, download_finish, upload_finish):
    download_duration = (download_finish - start).total_seconds()
    upload_duration = (upload_finish - download_finish).total_seconds()
    down_h, down_m, down_s = seconds_to_readable(download_duration)
    up_h, up_m, up_s = seconds_to_readable(upload_duration)
    total_h, total_m, total_s = seconds_to_readable(download_duration + upload_duration)
    print("SUMMARY:")
    print(f"Start: {start}")
    print(f"Download Finished: {download_finish}")
    print(f"Upload Finished: {upload_finish}")
    print(f"Download Duration: {down_h} hrs, {down_m} minutes, {down_s} seconds")
    print(f"Upload Duration: {up_h} hrs, {up_m} minutes, {up_s} seconds")
    print(f"Total Duration: {total_h} hrs, {total_m} minutes, {total_s} seconds")

def main():
    tz = ZoneInfo('US/Eastern')
    script_start = datetime.utcnow().replace(tzinfo=tz)
    # Establish connection to AspirEDU's S3 Resource
    aspire_s3_resource, aspire_s3_client = get_s3(
        ASPIRE_AWS_ACCESS_KEY_ID, ASPIRE_AWS_SECRET_ACCESS_KEY
    )

    # Connect to AspirEDU backup Bucket
    aspire_bucket = aspire_s3_resource.Bucket("aspiredu-pgbackups")

    # Get Cluster information from CrunchyBridge
    clusters = get_crunchy_clusters()
    for cluster in clusters:
        if cluster["name"] in CLUSTERS_TO_BACKUP:
            download_path = f"{LOCAL_TEMP_DOWNLOADS_PATH}{cluster['name']}"
            backup_info = get_cluster_backup_info(cluster["id"])

            download_env = {
                "AWS_ACCESS_KEY_ID": backup_info["aws"]["s3_key"],
                "AWS_SECRET_ACCESS_KEY": backup_info["aws"]["s3_key_secret"],
                "AWS_SESSION_TOKEN": backup_info["aws"]["s3_token"],
            }
            crunchy_backup_prefix = f"/backup/{backup_info['stanza']}"

            recursive_path_suffixes = [
                "/archive",
                f"{crunchy_backup_prefix}/backup.history",
            ]
            file_path_suffixes = [
                f"{crunchy_backup_prefix}/backup.info",
                f"{crunchy_backup_prefix}/backup.info.copy",
            ]

            # If a target backup name was specified, check the backup is available
            # and only copy that backup to AspirEDU's S3 Bucket
            if args.target:
                if args.target in [backup["name"] for backup in backup_info["backups"]]:
                    if not backup_exists(
                        aspire_s3_client, aspire_bucket, cluster["name"], args.target
                    ):
                        recursive_path_suffixes.append(
                            f"{crunchy_backup_prefix}/{args.target}"
                        )
                    else:
                        print(f"Target backup already exists in AspirEDU S3 Bucket")
                        exit(0)
                else:
                    print(
                        f"Target backup name {args.target} was not found in list of available CrunchyBridge"
                        f" backups for {cluster['name']}"
                    )
                    exit(0)
            else:
                # Determine if there are any new CrunchyBridge backups to move
                has_new_backup = False
                for backup in backup_info["backups"]:
                    if not backup_exists(
                        aspire_s3_client, aspire_bucket, cluster["name"], backup["name"]
                    ):
                        has_new_backup = True
                        print(
                            f"{cluster['name']}: Backup {backup['name']} not found in AspirEDU Bucket... Adding to download list!"
                        )
                        recursive_path_suffixes.append(
                            f"{crunchy_backup_prefix}/{backup['name']}"
                        )
                if not has_new_backup:
                    print("No new backups found!! Exiting script :)")
                    exit(0)

            crunchy_s3_path = f's3://{backup_info["aws"]["s3_bucket"]}/{backup_info["cluster_id"]}/{backup_info["stanza"]}'

            command_lists = [
                [
                    "aws",
                    "s3",
                    "cp",
                    f"{crunchy_s3_path}{recursive_path_suffix}",
                    f"{download_path}{recursive_path_suffix}",
                    "--recursive",
                ]
                for recursive_path_suffix in recursive_path_suffixes
            ]
            command_lists.extend(
                [
                    [
                        "aws",
                        "s3",
                        "cp",
                        f"{crunchy_s3_path}{path_suffix}",
                        f"{download_path}{path_suffix}",
                    ]
                    for path_suffix in file_path_suffixes
                ]
            )

            for i, command_list in enumerate(command_lists):
                command = " ".join(command_list)

                download_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=download_env,
                    shell=True,
                )

                watch_process_logs(download_process)
                print(f"{i + 1} / {len(command_lists)} downloads complete!")

            download_finish = datetime.utcnow().replace(tzinfo=tz)

            upload_all_files_in_dir(
                download_path,
                backup_info["stanza"],
                aspire_bucket,
                cluster["name"],
                BASE_S3_PREFIX,
            )

            upload_finish = datetime.utcnow().replace(tzinfo=tz)
            if args.delete:
                delete_all_files_in_dir(download_path)
            else:
                print(
                    f"The 'delete' option was not specified so the backup files will remain "
                    "in local storage."
                )
            
            summarize(script_start, download_finish, upload_finish)


if __name__ == "__main__":
    main()
