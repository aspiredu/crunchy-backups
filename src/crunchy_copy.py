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
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from src.s3 import get_s3
from src.schedule import is_valid_saturday

# ENV Variables
load_dotenv()
CRUNCHY_API_KEY = os.getenv("CRUNCHY_API_KEY")
CRUNCHY_TEAM_ID = os.getenv("CRUNCHY_TEAM_ID")

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")

LOCAL_TEMP_DOWNLOADS_PATH = os.getenv("LOCAL_TEMP_DOWNLOADS_PATH", "tmp/")

# The v2 directory is necessary so that we can more easily delete the other
# backups when all have been converted to our the format that either includes
# the WAL in the daily_backup/pg_data/pg_wal directory or the WAL in the
# archive directory is limited to what is necessary for the specific
# daily backup. Eventually v2 should be the only thing in the crunchybridge
# directory.
S3_BACKUP_DEST_PREFIX = os.getenv("S3_BACKUP_DEST_PREFIX", "crunchybridge/v2/")
SENTRY_DSN = os.getenv("SENTRY_DSN")

# Recommended values are:
# testing: "ONEZONE_IA"
# production: "DEEP_ARCHIVE"
STORAGE_CLASS = os.getenv("S3_STORAGE_CLASS", "DEEP_ARCHIVE")

STAGING_BACKENDS = ["aspirestaging", "aspiredu-stg"]
AU_BACKENDS = ["aspiredu-au"]
TZ = ZoneInfo("US/Eastern")


class CantFindCrunchyBridgeCluster(ValueError):
    pass


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


def three_years_from_now():
    return datetime.now(TZ) + relativedelta(years=3)


def get_cluster_backup_info(cluster_id: str, backup_target: str) -> dict:
    """Fetch the cluster's backup information from CrunchyBridge.

    This combines the backup-token information with the backup
    token into a single dictionary.
    """
    headers = {
        "Authorization": f"Bearer {CRUNCHY_API_KEY}",
    }
    backup_tokens = requests.post(
        f"https://api.crunchybridge.com/clusters/{cluster_id}/backup-tokens",
        headers=headers,
    )
    backup_tokens.raise_for_status()
    backup_info = requests.get(
        f"https://api.crunchybridge.com/clusters/{cluster_id}/backups"
        "?order=desc&order_field=name",
        headers=headers,
    )
    backup_info.raise_for_status()
    response = json.loads(backup_tokens.content.decode("utf-8"))
    backup_info = json.loads(backup_info.content.decode("utf-8"))
    # Look up the specific backup for the given target.
    response["backup"] = [
        backup for backup in backup_info["backups"] if backup["name"].startswith(backup_target)
    ][0]
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


def upload_all_files_in_dir(source_dir, bucket, prefix):
    print("Uploading files...")
    expiration = three_years_from_now()
    for root, _, files in os.walk(source_dir):
        for file in files:
            full_path = os.path.join(root, file)

            # Set up the file structure for S3
            new_file_key = f"{prefix}{full_path[len(source_dir):]}"
            print(f"Uploading... {new_file_key}")
            bucket.upload_file(
                os.path.join(root, file),
                new_file_key,
                ExtraArgs={"Expires": expiration, "StorageClass": STORAGE_CLASS},
            )
    return


def delete_all_files_in_dir(source_dir):
    print("Cleaning up!!")
    shutil.rmtree(source_dir, ignore_errors=True)


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
    def __init__(
        self, bucket_name: str, cluster_name: str, backup_target: str, dry_run: bool = False
    ):
        """

        :param bucket_name: The name of the bucket to copy to.
        :param cluster_name: The name of the CrunchyBridge cluster that the backup is from.
        :param backup_target: The date prefix for the backup we're targeting, such as `20200101`
        """
        self.s3_resource, self.s3 = get_s3(ASPIRE_AWS_ACCESS_KEY_ID, ASPIRE_AWS_SECRET_ACCESS_KEY)
        self.bucket = self.s3_resource.Bucket(bucket_name)
        self.backup_target = backup_target
        self.cluster = self.get_cluster(cluster_name)
        self.backup_info = get_cluster_backup_info(
            self.cluster["id"], backup_target=self.backup_target
        )
        self.dry_run = dry_run

    @staticmethod
    def get_cluster(cluster_name: str) -> dict:
        """Find the cluster from the CrunchyBridge API with the given name"""
        for cluster in get_crunchy_clusters():
            if cluster["name"] == cluster_name:
                return cluster
        raise CantFindCrunchyBridgeCluster("Could not find cluster with the given name")

    @staticmethod
    def s3_copy_command(src, dest, relative_path) -> str:
        command = f"aws s3 cp {src}{relative_path} {dest}{relative_path}"
        if relative_path.endswith("/"):
            # Any directory needs to be recursive
            command += " --recursive"
        return command

    def _copy_paths(self, file_paths: list[str]):
        """
        This downloads the files from the CrunchyBridge S3 to a local directory,
        then uploads them to our S3 bucket.

        :param file_paths: A list of relative file paths. If the path ends with
                           a `/`, it will be treated as a directory and its
                           contents will be copied recursively.
        """
        crunchy_s3_path = (
            f's3://{self.backup_info["aws"]["s3_bucket"]}/'
            f'{self.backup_info["cluster_id"]}/{self.backup_info["stanza"]}'
        )
        download_path = f"{LOCAL_TEMP_DOWNLOADS_PATH}{self.cluster['name']}"
        dest_s3_path = f"{S3_BACKUP_DEST_PREFIX}{self.cluster['name']}/{self.backup_target}"

        download_env = {
            "AWS_ACCESS_KEY_ID": self.backup_info["aws"]["s3_key"],
            "AWS_SECRET_ACCESS_KEY": self.backup_info["aws"]["s3_key_secret"],
            "AWS_SESSION_TOKEN": self.backup_info["aws"]["s3_token"],
        }

        if self.dry_run:
            print("Dry run only.")
            print(f"Downloading from: {crunchy_s3_path}")
            print(f"Downloading to: {download_path}")
            print(f"Uploading to: {dest_s3_path}")
            print("Commands: \n")

        for i, filepath in enumerate(file_paths):
            command = self.s3_copy_command(
                src=crunchy_s3_path,
                dest=download_path,
                relative_path=filepath,
            )

            if self.dry_run:
                print(command)
            else:
                download_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    env=download_env,
                    shell=True,
                )

                watch_process_logs(download_process)
                print(f"{i + 1} / {len(file_paths)} downloads complete! Proceeding to upload...")

                upload_all_files_in_dir(download_path, self.bucket, prefix=dest_s3_path)
                delete_all_files_in_dir(download_path)

    def _get_copy_paths(self):
        """
        Get the relative paths of files we need to copy from CrunchyBridge to S3.

        We need to store the following files and folders as a snapshot in our
        S3 bucket. Only the files and folders listed in below should be copied.
        There are  =many other files in the structure that we don't need.
        Since we will be storing this for years we want to only store what's
        needed. For example, the archive/ folder has the entire WAL for the
        last 10 days. We don't need that (as long as CB is using
        ``--copy-archive``) because it's stored in the pg_data/pg_wal/ folder.

        This is a description of the file structure of a CrunchyBridge backup.

        cluster/
        ├─ archive/  # This is the WAL that is stored while the backup is created
        │   └─ backup_stanza/
        │      └─ archive.info
        └─ backup/  # This is the physical backup created each day
           └─ backup_stanza/
              ├─ backup.history/
              │  └─ */*
              ├─ backup.info
              ├─ backup.info.copy
              └─ 20230101-010000F/
                 └─ */*
        """

        stanza = self.backup_info["stanza"]
        backup_slug = self.backup_info["backup"]["name"]
        files_to_copy = [
            f"/archive/{stanza}/archive.info",
            f"/backup/{stanza}/backup.info",
            f"/backup/{stanza}/backup.copy",
            # recursive folders
            f"/backup/{stanza}/backup.history/",
            f"/backup/{stanza}/{backup_slug}/",
        ]
        return files_to_copy

    def process(self):
        script_start = datetime.utcnow().replace(tzinfo=TZ)

        self._copy_paths(self._get_copy_paths())

        summarize(
            script_start,
            datetime.utcnow().replace(tzinfo=TZ),
        )

        # Signal Dead Man's Snitch and terminate
        signal_dead_mans_snitch(self.cluster["name"])


def validate_target(target: Optional[str] = None):
    """
    Determine if the backup target is valid.

    This should check to see if the string representation of the date
    is a date and whether it's a valid Saturday.

    It should return the string version of the date so it can
    be used in file paths with S3.
    """
    if not target:
        target_date = datetime.now()
    else:
        try:
            target_date = datetime.strptime(target, "%Y%m%d")
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{target} is not a valid date. It must be in the format YYYYMMDD."
            )

    if not is_valid_saturday(target_date):
        raise ValueError(f"Today {target_date} is not a valid Saturday")
    return target_date.strftime("%Y%m%d")


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
        "-c",
        "--cluster",
        required=True,
        help="The name of the database cluster to pretend to create",
    )
    parser.add_argument(
        "-t",
        "--target",
        required=False,
        help="(Optional) The name of a specific backup to target. Defaults to today's backups.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="(Optional) This won't download or upload the files, instead it will print the paths.",
    )
    args = parser.parse_args()
    bucket_name = (
        "aspiredu-pgbackups" if args.cluster not in AU_BACKENDS else "aspiredu-pgbackups-au"
    )
    try:
        backup_target = validate_target(args.target)
    except ValueError:
        pass
    else:
        # If we have a valid Saturday, process the data.
        CrunchyCopy(
            bucket_name, args.cluster, backup_target=backup_target, dry_run=args.dry_run
        ).process()
    exit(0)


if __name__ == "__main__":
    main()
