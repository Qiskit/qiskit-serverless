# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

from unittest.mock import MagicMock
from datetime import datetime, timezone

from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials


def _make_client() -> COSClient:
    provider = MagicMock()
    provider.config.region = "us-south"
    creds = CosHmacCredentials(access_key_id="ak", secret_access_key="sk")
    client = COSClient(client_provider=provider, credentials=creds)
    return client


def test_list_with_metadata_returns_key_size_last_modified():
    client = _make_client()
    ts = datetime(2024, 5, 10, 14, 32, 0, tzinfo=timezone.utc)
    mock_s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "users/alice/fn/data/file.py", "Size": 4200, "LastModified": ts}]}
    ]
    mock_s3.get_paginator.return_value = paginator
    client._s3 = mock_s3

    result = client.list_with_metadata(bucket="my-bucket", prefix="users/alice/fn/data/")

    assert len(result) == 1
    assert result[0]["key"] == "users/alice/fn/data/file.py"
    assert result[0]["size"] == 4200
    assert result[0]["last_modified"] == ts


def test_list_with_metadata_empty_prefix_returns_empty():
    client = _make_client()
    mock_s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [{}]  # no Contents key
    mock_s3.get_paginator.return_value = paginator
    client._s3 = mock_s3

    result = client.list_with_metadata(bucket="my-bucket", prefix="nonexistent/prefix/")

    assert result == []
