"""
Migrate our backups from a complete copy of CrunchyBridge's rolling 10 day window
to a snapshot of backups of the first and third Saturday's of each month.

The backup directories already contain the reduced backups. This needs to
convert it over to the new location.

Iterate through folders in our backup folders
    cluster/
    ├─ archive/ # This is the WAL that is stored while the backup is created
    │   └─ backup_stanza/
    │      ├─ 15-1/
    │      │   └─ 0000000100000821/
    │      │      └─ 00000001000008210000001D.lz4
    │      └─ archive.info
    └─ backup/ # This is the physical backup created each day
       └─ backup_stanza/
          ├─ backup.history/
          ├─ backup.info
          ├─ backup.info.copy
          └─ 20230101-010000F/
             ├─ backup.manifest
             ├─ backup.manifest.copy
             └─ pg_data/

Look through the backup.manifest file for
backup-archive-start and backup-archive-stop
Find all files between these two values.

"""
import argparse
import os
from datetime import datetime
from typing import Optional

import sentry_sdk
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from src.delete_backups import CRUNCHYBRIDGE_BACKUP_PATTERN
from src.s3 import get_s3

# ENV Variables
load_dotenv()

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")
SENTRY_DSN = os.getenv("SENTRY_DSN")


def lsn_in_range(start_hex, end_hex):
    for value_decimal in range(int(start_hex, 16), int(end_hex, 16) + 1):
        value_hex = hex(value_decimal)[2:].upper()
        yield value_hex.zfill(16)


def parse_manifest(body) -> (str, str):
    """
    Parse start and stop LSN from backup.manifest

    The typical format of these files is:


        [backrest]
        backrest-format=5
        backrest-version="2.45"

        [backup]
        backup-archive-start="00000001000008210000001D"
        backup-archive-stop="00000001000008210000001F"
        backup-label="20230916-010001F"
        backup-lsn-start="821/1D000028"
        backup-lsn-stop="821/1F0B73F0"
    """
    start = None
    stop = None
    for line in body.read().decode("utf-8").splitlines():
        if line.startswith("backup-archive-start"):
            start = line.split("=")[1].strip().replace('"', "")
        if line.startswith("backup-archive-stop"):
            stop = line.split("=")[1].strip().replace('"', "")
        if start and stop:
            break
    if not start or not stop:
        raise ValueError("Could not find start or stop LSN in manifest")
    return start, stop


def get_backups_to_migrate(s3, bucket, cluster=None):
    cluster_prefixes = [
        f'{common_prefix["Prefix"]}'
        for common_prefix in s3.list_objects(Bucket=bucket, Prefix="crunchybridge/", Delimiter="/")[
            "CommonPrefixes"
        ]
        if not cluster or common_prefix["Prefix"].endswith(cluster + "/")
    ]
    for cluster_prefix in cluster_prefixes:
        stanza_prefixes = [
            common_prefix["Prefix"]
            for common_prefix in s3.list_objects(
                Bucket=bucket, Prefix=cluster_prefix + "backup/", Delimiter="/"
            )["CommonPrefixes"]
        ]
        for stanza_prefix in stanza_prefixes:
            for backup_folder_prefix in s3.list_objects(
                Bucket=bucket, Prefix=stanza_prefix, Delimiter="/"
            )["CommonPrefixes"]:
                if backup_folder_prefix["Prefix"].endswith("backup.history/"):
                    continue
                yield stanza_prefix, backup_folder_prefix["Prefix"]


def archive_files_to_copy(s3, bucket, stanza_prefix, backup_folder_prefix):
    files_to_copy = [
        f"{stanza_prefix}archive.info",
        f"{stanza_prefix}archive.info.copy",
    ]
    response = s3.get_object(Bucket=bucket, Key=backup_folder_prefix + "backup.manifest")
    start, stop = parse_manifest(response["Body"])
    start_lsn = int(start, 16)
    stop_lsn = int(stop, 16)

    archive_prefixes = s3.list_objects(Bucket=bucket, Prefix=f"{stanza_prefix}", Delimiter="/")[
        "CommonPrefixes"
    ]
    for obj in archive_prefixes:
        archive_prefix = obj["Prefix"]
        short_lsns = set()
        # Iterate over 16 digit hex number.
        for shortened_lsn in lsn_in_range(start[:16], stop[:16]):
            paginator = s3.get_paginator("list_objects")
            page_iterator = paginator.paginate(
                Bucket=bucket,
                PaginationConfig={"PageSize": 1000},
                Prefix=f"{archive_prefix}{shortened_lsn}/",
            )
            for page in page_iterator:
                for obj in page["Contents"]:
                    filename = obj["Key"].split("/")[-1]
                    file_lsn = int(filename[:24], 16)
                    # Check is LSN is in the start/stop range
                    if start_lsn <= file_lsn <= stop_lsn and filename.endswith(".lz4"):
                        files_to_copy.append(obj["Key"])
                        short_lsns.add(shortened_lsn)
    return files_to_copy


def backup_files_to_copy(s3, bucket, stanza_prefix, backup_folder_prefix):
    def _find_all_keys(prefix):
        keys = []
        paginator = s3.get_paginator("list_objects")
        page_iterator = paginator.paginate(
            Bucket=bucket, PaginationConfig={"PageSize": 1000}, Prefix=prefix
        )
        for page in page_iterator:
            for obj in page["Contents"]:
                keys.append(obj["Key"])
        return keys

    return (
        [
            f"{stanza_prefix}backup.info",
            f"{stanza_prefix}backup.info.copy",
        ]
        + _find_all_keys(f"{stanza_prefix}backup.history/")  # noqa: W503
        + _find_all_keys(backup_folder_prefix)  # noqa: W503
    )


def copy_files(s3, bucket, files_to_copy, backup_folder, storage_class, dry_run=False):
    backup_date = datetime.strptime(backup_folder, "%Y%m%d").date()
    expiration = backup_date + relativedelta(years=3)
    for src in files_to_copy:
        cb, cluster, *segments = src.split("/")
        relative = "/".join(segments)
        src = f"{cb}/{cluster}/{relative}"
        dest = f"{cb}/v2/{cluster}/{backup_folder}/{relative}"
        if not dry_run:
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": src},
                Key=dest,
                Expires=expiration.isoformat(),
                StorageClass=storage_class,
            )
        else:
            # Dry run, print the copy commands
            print(
                f"s3 copy {src} {dest} StorageClass={storage_class} Expires={expiration.isoformat()}"
            )


def migrate_backups(
    *,
    cluster: Optional[str],
    target: Optional[str],
    storage_class: Optional[str],
    dry_run: bool = False,
):
    s3_resource, s3 = get_s3(None, None)
    for bucket in ["aspiredu-pgbackups", "aspiredu-pgbackups-au"]:
        for stanza_prefix, bucket_folder_prefix in get_backups_to_migrate(s3, bucket, cluster):
            backup_folder = None
            if match := CRUNCHYBRIDGE_BACKUP_PATTERN.match(bucket_folder_prefix.split("/")[-2]):
                backup_folder = match.groups()[0]
                if target and target != backup_folder:
                    continue
            if not backup_folder:
                continue
            files_to_copy = backup_files_to_copy(
                s3, bucket, stanza_prefix, bucket_folder_prefix
            ) + archive_files_to_copy(
                s3, bucket, stanza_prefix.replace("/backup/", "/archive/"), bucket_folder_prefix
            )
            copy_files(
                s3,
                bucket,
                files_to_copy,
                backup_folder,
                storage_class=storage_class,
                dry_run=dry_run,
            )


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
        prog="S3 Database Backup Cleaner",
        description="Removes backups according to AspirEDU's retention policy",
    )

    parser.add_argument(
        "--cluster",
        required=False,
        help="(Optional) The name of the database cluster to pretend to create",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="(Optional) Don't delete any data, but print out key paths.",
        default=False,
    )
    parser.add_argument(
        "--storage-class",
        help="(Optional) The storage class to use for the migrated files.",
        default="ONEZONE_IA",
    )
    parser.add_argument(
        "--target",
        required=False,
        help="(Optional) The backup to target (YYYYMMDD)",
    )
    args = parser.parse_args()
    migrate_backups(
        cluster=args.cluster,
        target=args.target,
        storage_class=args.storage_class,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
