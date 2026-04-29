"""Tests for RayCOSClient."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from botocore.exceptions import ClientError

from core.services.storage.abstract_cos_client import COSError
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.ray_cos_client import RayCOSClient


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "op")


@pytest.fixture
def s3():
    mock = MagicMock()
    with patch.object(RayCOSClient, "_boto3_client", new_callable=PropertyMock, return_value=mock):
        yield mock


class TestGetObjectBytes:
    def test_returns_none_on_no_such_key(self, s3):
        s3.get_object.side_effect = _client_error("NoSuchKey")
        assert RayCOSClient().get_object_bytes("key") is None

    def test_raises_cos_error_on_other_client_error(self, s3):
        s3.get_object.side_effect = _client_error("AccessDenied")
        with pytest.raises(COSError):
            RayCOSClient().get_object_bytes("key")


class TestGetObject:
    def test_decodes_bytes_to_str(self, s3):
        s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"hello")}
        assert RayCOSClient().get_object("key") == "hello"

    def test_returns_none_when_key_not_found(self, s3):
        s3.get_object.side_effect = _client_error("NoSuchKey")
        assert RayCOSClient().get_object("key") is None


class TestPutObjectBytes:
    def test_raises_cos_error_on_client_error(self, s3):
        s3.put_object.side_effect = _client_error("InternalError")
        with pytest.raises(COSError):
            RayCOSClient().put_object_bytes("key", b"data")


class TestPutObject:
    def test_encodes_str_to_utf8_bytes(self, s3):
        RayCOSClient().put_object("key", "héllo")
        assert s3.put_object.call_args.kwargs["Body"] == "héllo".encode("utf-8")


class TestDeleteObject:
    def test_returns_true_on_success(self, s3):
        assert RayCOSClient().delete_object("key") is True

    def test_returns_false_on_client_error(self, s3):
        s3.delete_object.side_effect = _client_error("InternalError")
        assert RayCOSClient().delete_object("key") is False


class TestListObjects:
    def test_returns_keys_from_contents(self, s3):
        s3.list_objects_v2.return_value = {"Contents": [{"Key": "a/b.txt"}, {"Key": "a/c.txt"}]}
        assert RayCOSClient().list_objects("a/") == ["a/b.txt", "a/c.txt"]

    def test_returns_empty_list_when_no_contents(self, s3):
        s3.list_objects_v2.return_value = {}
        assert RayCOSClient().list_objects("a/") == []

    def test_raises_cos_error_on_client_error(self, s3):
        s3.list_objects_v2.side_effect = _client_error("InternalError")
        with pytest.raises(COSError):
            RayCOSClient().list_objects("a/")
