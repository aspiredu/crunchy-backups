import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime
from http import HTTPStatus
from typing import Optional
from zoneinfo import ZoneInfo

import requests
import sentry_sdk
from dotenv import load_dotenv

from src.s3 import get_s3

# ENV Variables
load_dotenv()
CRUNCHY_API_KEY = os.getenv("CRUNCHY_API_KEY")
CRUNCHY_TEAM_ID = os.getenv("CRUNCHY_TEAM_ID")

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")

LOCAL_TEMP_DOWNLOADS_PATH = os.getenv("LOCAL_TEMP_DOWNLOADS_PATH")
BASE_S3_PREFIX = os.getenv("BASE_S3_PREFIX")
SENTRY_DSN = os.getenv("SENTRY_DSN")

STAGING_BACKENDS = ["aspirestaging", "aspiredu-stg"]
AU_BACKENDS = ["aspiredu-au"]
TZ = ZoneInfo("US/Eastern")


def get_crunchy_clusters():
    headers = {
        "Authorization": f"Bearer {CRUNCHY_API_KEY}",
    }
    response = requests.get(
        f"https://api.crunchybridge.com/clusters?team_id={CRUNCHY_TEAM_ID}",
        headers=headers,
    )
    if not response.status_code == HTTPStatus.OK:
        response.raise_for_status()
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
    if not backup_tokens.status_code == HTTPStatus.OK:
        backup_tokens.raise_for_status()
    if not backup_info.status_code == HTTPStatus.OK:
        backup_info.raise_for_status()
    backup_info = json.loads(backup_info.content.decode("utf-8"))
    response["backups"] = backup_info["backups"]
    return response


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


def backup_exists(s3, bucket, cluster_name, stanza, backup_name):
    if not backup_name.endswith("/"):
        backup_name = backup_name + "/"
    prefix = f"crunchybridge/{cluster_name}/backup/{stanza}/{backup_name}"
    resp = s3.list_objects(Bucket=bucket.name, Prefix=prefix, MaxKeys=1)
    return "Contents" in resp


def seconds_to_readable(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return h, m, s


def summarize(start, finish):
    print("SUMMARY:")
    print(f"Start: {start}")
    print(f"Finish: {finish}")
    total_h, total_m, total_s = seconds_to_readable((finish - start).total_seconds())
    print(f"Total Duration: {total_h} hrs, {total_m} minutes, {total_s} seconds")


def signal_dead_mans_snitch(cluster: str):
    print("Signaling Dead Man's Snitch...")
    if cluster not in STAGING_BACKENDS:
        with open("./src/backend-snitch-map.json") as json_map:
            backend_snitch_map = json.load(json_map)
        res = requests.post(backend_snitch_map[cluster], data={"m": "Completed"})
        return res
    else:
        return


class CrunchyCopy:
    def __init__(self, bucket_name: str, cluster_name: str, backup_target: Optional[str] = None):
        self.s3, self.s3_client = get_s3(ASPIRE_AWS_ACCESS_KEY_ID, ASPIRE_AWS_SECRET_ACCESS_KEY)
        self.bucket = self.s3.Bucket(bucket_name)
        self.backup_target = backup_target
        for cluster in get_crunchy_clusters():
            if cluster["name"] != cluster_name:
                continue
            self.cluster = cluster
            self.backup_info = get_cluster_backup_info(cluster["id"])
            break

    def _copy_paths(self, recursive_paths, file_paths):
        crunchy_s3_path = (
            f's3://{self.backup_info["aws"]["s3_bucket"]}/'
            f'{self.backup_info["cluster_id"]}/{self.backup_info["stanza"]}'
        )
        download_path = f"{LOCAL_TEMP_DOWNLOADS_PATH}{self.cluster['name']}"

        command_lists = [
            [
                "aws",
                "s3",
                "cp",
                f"{crunchy_s3_path}{path}",
                f"{download_path}{path}",
                "--recursive",
            ]
            for path in recursive_paths
        ] + [
            [
                "aws",
                "s3",
                "cp",
                f"{crunchy_s3_path}{path}",
                f"{download_path}{path}",
            ]
            for path in file_paths
        ]

        download_env = {
            "AWS_ACCESS_KEY_ID": self.backup_info["aws"]["s3_key"],
            "AWS_SECRET_ACCESS_KEY": self.backup_info["aws"]["s3_key_secret"],
            "AWS_SESSION_TOKEN": self.backup_info["aws"]["s3_token"],
        }

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
            print(f"{i + 1} / {len(command_lists)} downloads complete! Proceeding to upload...")

            upload_all_files_in_dir(
                download_path,
                self.backup_info["stanza"],
                self.bucket,
                self.cluster["name"],
                BASE_S3_PREFIX,
            )
            delete_all_files_in_dir(download_path)

    def _get_copy_paths(self):
        crunchy_backup_prefix = f"/backup/{self.backup_info['stanza']}"

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
        if self.backup_target:
            if self.backup_target in [backup["name"] for backup in self.backup_info["backups"]]:
                if not backup_exists(
                    self.s3_client,
                    self.bucket,
                    self.cluster["name"],
                    self.backup_info["stanza"],
                    self.backup_target,
                ):
                    recursive_path_suffixes.append(f"{crunchy_backup_prefix}/{self.backup_target}")
                else:
                    print("Target backup already exists in AspirEDU S3 Bucket")
                    return [], []
            else:
                print(
                    f"Target backup name {self.backup_target} was not found in list of available"
                    f" CrunchyBridge backups for {self.cluster['name']}"
                )
                return [], []
        else:
            # Determine if there are any new CrunchyBridge backups to move
            has_new_backup = False
            for backup in self.backup_info["backups"]:
                if not backup_exists(
                    self.s3_client,
                    self.bucket,
                    self.cluster["name"],
                    self.backup_info["stanza"],
                    backup["name"],
                ):
                    has_new_backup = True
                    print(
                        f"{self.cluster['name']}: Backup {backup['name']} not found in AspirEDU "
                        f"Bucket... Adding to download list!"
                    )
                    recursive_path_suffixes.append(f"{crunchy_backup_prefix}/{backup['name']}")
            if not has_new_backup:
                print("No new backups found!! Exiting script :)")
                return [], []
        return recursive_path_suffixes, file_path_suffixes

    def process(self):
        script_start = datetime.utcnow().replace(tzinfo=TZ)

        recursive_paths, file_paths = self._get_copy_paths()
        self._copy_paths(recursive_paths, file_paths)

        summarize(
            script_start,
            datetime.utcnow().replace(tzinfo=TZ),
        )

        # Signal Dead Man's Snitch and terminate
        signal_dead_mans_snitch(self.cluster["name"])


def main():
    # Optionally set up Sentry Integration
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=1.0,
        )

    # Parse Arguments
    parser = argparse.ArgumentParser(
        prog="CrunchyBridge Backup",
        description="Moves backups from CrunchyBridge's S3 Buckets to " "AspirEDU's S3 Bucket",
    )

    parser.add_argument(
        "-b", "--bucket", dest="bucket_name", required=True, help="The name of the bucket."
    )
    parser.add_argument(
        "-c",
        "--cluster",
        required=False,
        help="(Optional) The name of the database cluster to pretend to create",
    )
    parser.add_argument(
        "-t", "--target", help="(Optional) The name of a specific backup to target."
    )
    args = parser.parse_args()
    bucket_name = (
        "aspiredu-pgbackups" if args.cluster not in AU_BACKENDS else "aspiredu-pgbackups-au"
    )
    CrunchyCopy(bucket_name, args.cluster, args.target).process()
    exit(0)


if __name__ == "__main__":
    main()
