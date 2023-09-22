"""
Delete backups in S3 bucket according to our Data Rention Policy:
https://github.com/aspiredu/aspiredu/issues/7421
"""
import argparse
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
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


def is_saturday(value: date) -> bool:
    """Determine if date is a Saturday"""
    return value.weekday() == 5


@lru_cache(maxsize=None)
def saturdays_for_the_past_year() -> set[date]:
    """Find all Saturdays between from today to 1 year ago"""
    start = date.today()
    cut_off = start - relativedelta(years=1)
    return set(
        d.date() for d in rrule.rrule(rrule.WEEKLY, byweekday=SA(1), dtstart=cut_off, until=start)
    )


@lru_cache(maxsize=None)
def first_saturdays_of_month_year1_to_year3() -> set[date]:
    """Find first Saturday of each month between from 1 year to 3 years"""
    today = date.today()
    start = today - relativedelta(years=1)
    cut_off = today - relativedelta(years=3)
    return set(
        d.date() for d in rrule.rrule(rrule.MONTHLY, byweekday=SA(1), dtstart=cut_off, until=start)
    )


def meets_retention_policy(value: date):
    today = date.today()
    # We want to keep every backup for the first two weeks.
    if (today - timedelta(weeks=2)) < value <= today:
        return True
    if is_saturday(value):
        if value in saturdays_for_the_past_year():
            return True
        if value in first_saturdays_of_month_year1_to_year3():
            return True
    return False


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
    :param bucket: The s3 Bucket instance
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
        groupings = [
            common_prefix["Prefix"]
            for common_prefix in s3.list_objects(
                Bucket=bucket.name, Prefix=cluster_prefix, Delimiter="/"
            )["CommonPrefixes"]
        ]
        for grouping in groupings:
            for backup_folder_prefix in s3.list_objects(
                Bucket=bucket.name, Prefix=grouping, Delimiter="/"
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
        help="(Optional) Remove more than just the expected day's expired data. If more than 3 backups are found this will cause an exception to be raised.",
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
