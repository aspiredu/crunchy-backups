import os
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine

from .crunchy_copy import (
    CantFindCrunchyBridgeCluster,
    CrunchyCopy,
    upload_all_files_in_dir,
)

utc_tz = ZoneInfo("UTC")
edt_tz = ZoneInfo("US/Eastern")


def touch(path):
    with open(path, "a"):
        os.utime(path, None)


@pytest.fixture
def patch_storage_class(mocker):
    return mocker.patch("src.crunchy_copy.STORAGE_CLASS", "TEST_STORAGE")


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_upload_all_files_in_dir(mocker, patch_storage_class):
    mock_bucket = mocker.Mock()
    # create temp dir
    shutil.rmtree("tmp", ignore_errors=True)
    os.makedirs("tmp/sub1")
    touch("tmp/file.txt")
    touch("tmp/sub1/file.txt")
    upload_all_files_in_dir("tmp", mock_bucket, prefix="pre-")

    assert mock_bucket.upload_file.call_args_list == [
        mocker.call(
            "tmp/file.txt",
            "pre-/file.txt",
            ExtraArgs={
                "Expires": datetime(2022, 12, 31, 19, 0, tzinfo=edt_tz),
                "StorageClass": "TEST_STORAGE",
            },
        ),
        mocker.call(
            "tmp/sub1/file.txt",
            "pre-/sub1/file.txt",
            ExtraArgs={
                "Expires": datetime(2022, 12, 31, 19, 0, tzinfo=edt_tz),
                "StorageClass": "TEST_STORAGE",
            },
        ),
    ]


class TestCrunchyCopy:
    def test_get_cluster(self, mocker):
        mocked_get_crunchy_clusters = mocker.patch("src.crunchy_copy.get_crunchy_clusters")
        mocked_get_crunchy_clusters.return_value = [
            {"id": "cb-1", "name": "Cluster 1"},
            {"id": "cb-2", "name": "Cluster 2"},
        ]
        assert CrunchyCopy.get_cluster("Cluster 1") == {"id": "cb-1", "name": "Cluster 1"}
        with pytest.raises(CantFindCrunchyBridgeCluster):
            CrunchyCopy.get_cluster("Cluster 3")

    def test_s3_copy_command(self):
        assert CrunchyCopy.s3_copy_command("s3://b/p", "tmp", "/file.txt") == (
            "aws s3 cp s3://b/p/file.txt tmp/file.txt"
        )
        assert CrunchyCopy.s3_copy_command("s3://b/p", "tmp", "/dir/") == (
            "aws s3 cp s3://b/p/dir/ tmp/dir/ --recursive"
        )
