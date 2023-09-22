"""
This creates mock of our crunchy bridge backups in a S3 bucket.
This bucket can then be used by ``delete_backups`` for testing
to confirm that the correct backups are deleted.
"""
import argparse
import os
from datetime import date

import sentry_sdk
from dateutil import rrule
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from src.s3 import get_s3

# ENV Variables
load_dotenv()

ASPIRE_AWS_ACCESS_KEY_ID = os.getenv("ASPIRE_AWS_ACCESS_KEY_ID")
ASPIRE_AWS_SECRET_ACCESS_KEY = os.getenv("ASPIRE_AWS_SECRET_ACCESS_KEY")
SENTRY_DSN = os.getenv("SENTRY_DSN")


def get_test_dates():
    today = date.today()
    cut_off = today - relativedelta(years=3, months=2)
    for d in rrule.rrule(rrule.DAILY, dtstart=cut_off, until=today):
        yield d.date()


def create_s3_test_data(bucket_name, cluster):
    """
    Create s3 test files as per the file structure defined in backup_directories.
    """
    s3_resource, s3 = get_s3(ASPIRE_AWS_ACCESS_KEY_ID, ASPIRE_AWS_SECRET_ACCESS_KEY)
    bucket = s3_resource.Bucket(bucket_name)

    retain_cluster = f"{cluster}_retain"
    for d in get_test_dates():
        s3.put_object(
            Bucket=bucket.name,
            Key=f"crunchybridge/{cluster}/backup/abc123/{d.strftime('%Y%m%d')}-000000F/test.txt",
            Body=b"test file",
        )
        # Create data in a separate cluster that shouldn't be deleted.
        s3.put_object(
            Bucket=bucket.name,
            Key=f"crunchybridge/{retain_cluster}/backup/abc123/{d.strftime('%Y%m%d')}-000000F/test.txt",
            Body=b"test file",
        )
    # Create ancillary files that should stick around
    s3.put_object(
        Bucket=bucket.name,
        Key=f"crunchybridge/{cluster}/backup/abc123/backup.history/test.txt",
        Body=b"test file",
    )
    s3.put_object(
        Bucket=bucket.name,
        Key=f"crunchybridge/{cluster}/backup/abc123/backup.info",
        Body=b"test file",
    )
    s3.put_object(
        Bucket=bucket.name,
        Key=f"crunchybridge/{cluster}/backup/abc123/backup.info.copy",
        Body=b"test file",
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
        prog="S3 Database Backup Test Utility",
        description="Creates test backups for delete_backups",
    )

    parser.add_argument(
        "--bucket", dest="bucket_name", required=True, help="The name of the bucket."
    )
    parser.add_argument(
        "--cluster", required=True, help="The name of the database cluster to pretend to create"
    )
    args = parser.parse_args()
    create_s3_test_data(args.bucket_name, cluster=args.cluster)


if __name__ == "__main__":
    main()
