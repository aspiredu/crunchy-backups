"""
Delete backups in S3 bucket according to our Data Retention Policy:
https://github.com/aspiredu/aspiredu/issues/7421
"""
import argparse
import os
import re
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from itertools import chain

import sentry_sdk
from dateutil import rrule
from dateutil.relativedelta import SA, relativedelta
from dotenv import load_dotenv

from src.s3 import get_s3

# ENV Variables
load_dotenv()

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")
SENTRY_DSN = os.getenv("SENTRY_DSN")

CRUNCHYBRIDGE_BACKUP_PATTERN = re.compile(r"(\d{8})-\w*")


class TooManyDirectoriesForDeletion(Exception):
    pass


@lru_cache(maxsize=None)
def saturdays_for_the_past_three_years(value: date) -> set[date]:
    """Find all Saturdays between from value to 3 years ago"""
    cut_off = value - relativedelta(years=3)
    saturday_ruleset = rrule.rruleset()
    saturday_ruleset.rrule(
        rrule.rrule(rrule.MONTHLY, byweekday=SA(1), dtstart=cut_off, until=value)
    )
    saturday_ruleset.rrule(
        rrule.rrule(rrule.MONTHLY, byweekday=SA(3), dtstart=cut_off, until=value)
    )
    return {d.date() for d in saturday_ruleset}


def meets_retention_policy(value: date):
    return value in saturdays_for_the_past_three_years(date.today())


def delete_files(s3, bucket, prefix: str):
    paginator = s3.get_paginator("list_objects")
    page_iterator = paginator.paginate(
        Bucket=bucket.name, PaginationConfig={"PageSize": 1000}, Prefix=prefix
    )
    for page in page_iterator:
        s3.delete_objects(
            Bucket=bucket.name,
            Delete={"Objects": [{"Key": obj["Key"]} for obj in page["Contents"]]},
        )


def backup_directories(s3, bucket, cluster=None):
    """
    Find all the database cluster backup folders.

    Our S3 backup buckets are structured as follows:

    aspiredu-pgbackups/
    ├─ archive # Specific days we captured backups
    ├─ heroku # Heroku daily backups
    └─ crunchybridge/
       ├─ aspireprod/
       └─ cluster/
          ├─ archive # This is the WAL that is stored while the backup is created
          └─ backup # This is the physical backup created each day
             ├─ random_chars_for_folders/
             │  ├─ backup.history/
             │  ├─ backup.info
             │  ├─ backup.info.copy
             │  └─ 20230201-010000F/
             └─ more_random_char/
                ├─ backup.history/
                ├─ backup.info
                ├─ backup.info.copy
                ├─ 20230103-010000F/
                ├─ 20230102-010000F/
                └─ 20230101-010000F/

    We are looking to get:
    - 20230201-010000F
    - 20230103-010000F
    - 20230102-010000F
    - 20230101-010000F

    :param s3: The s3 client resource.
    :param bucket: The s3 Bucket instance.
    :param cluster: The database cluster name.
    :return list[str]: The collection of folder names that are used for daily backups.
    """
    cluster_prefixes = [
        f'{common_prefix["Prefix"]}backup/'
        for common_prefix in s3.list_objects(
            Bucket=bucket.name, Prefix="crunchybridge/", Delimiter="/"
        )["CommonPrefixes"]
        if not cluster or common_prefix["Prefix"].endswith(f"/{cluster}/")
    ]
    for cluster_prefix in cluster_prefixes:
        stanzas = [
            common_prefix["Prefix"]
            for common_prefix in s3.list_objects(
                Bucket=bucket.name, Prefix=cluster_prefix, Delimiter="/"
            )["CommonPrefixes"]
        ]
        for stanza in stanzas:
            for backup_folder_prefix in s3.list_objects(
                Bucket=bucket.name, Prefix=stanza, Delimiter="/"
            )["CommonPrefixes"]:
                yield cluster_prefix, backup_folder_prefix["Prefix"]


def enforce_retention_policy(
    bucket_name: str, cluster: str = None, clean_up_bucket: bool = False, dry_run: bool = False
):
    # Establish connection to AspirEDU's S3 Resource
    s3_resource, s3 = get_s3(ASPIRE_AWS_ACCESS_KEY_ID, ASPIRE_AWS_SECRET_ACCESS_KEY)

    # Connect to AspirEDU backup Bucket
    bucket = s3_resource.Bucket(bucket_name)
    to_delete = defaultdict(list)
    for backup_cluster, backup_directory_prefix in backup_directories(s3, bucket, cluster=cluster):
        directory = backup_directory_prefix.split("/")[-2]
        if match := CRUNCHYBRIDGE_BACKUP_PATTERN.match(directory):
            backup_date = datetime.strptime(match.groups()[0], "%Y%m%d").date()
            if not meets_retention_policy(backup_date):
                to_delete[backup_cluster].append(backup_directory_prefix)

    if any(len(directories) > 3 for directories in to_delete.values()) and not clean_up_bucket:
        # Our retention policy has three places where a backup may
        # get deleted. After the daily, weekly and monthly.
        # We should never have more than three backups being deleted
        # unless we skipped a day and need to clean up the backlog.
        # The purpose of this is to avoid programmatically deleting
        # everything.
        raise TooManyDirectoriesForDeletion()

    for directory_prefix in chain.from_iterable(to_delete.values()):
        if dry_run:
            print(directory_prefix)
        else:
            delete_files(s3, bucket, prefix=directory_prefix)


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
        "--bucket", dest="bucket_name", required=True, help="The name of the bucket."
    )
    parser.add_argument(
        "--cluster",
        required=False,
        help="(Optional) The name of the database cluster to pretend to create",
    )
    parser.add_argument(
        "--clean-up",
        dest="clean_up",
        action="store_true",
        help="(Optional) Remove more than just the expected day's expired data. "
        "If more than 3 backups are found this will cause an exception to be "
        "raised.",
        default=False,
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="(Optional) Don't delete any data, but print out key paths.",
        default=False,
    )
    args = parser.parse_args()
    enforce_retention_policy(
        args.bucket_name, cluster=args.cluster, clean_up_bucket=args.clean_up, dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
