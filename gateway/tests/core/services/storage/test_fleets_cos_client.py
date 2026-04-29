"""Tests for FleetsCOSClient."""

from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from botocore.exceptions import ClientError
from django.conf import settings

from core.services.storage.abstract_cos_client import COSError
from core.services.storage.enums.working_dir import WorkingDir
from core.services.storage.fleets_cos_client import FleetsCOSClient


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "op")


@contextmanager
def _patched_clients():
    users = MagicMock()
    partners = MagicMock()
    with patch.object(FleetsCOSClient, "_users_boto3_client", new_callable=PropertyMock, return_value=users):
        with patch.object(FleetsCOSClient, "_partners_boto3_client", new_callable=PropertyMock, return_value=partners):
            yield users, partners


@pytest.fixture
def s3_pair():
    with _patched_clients() as pair:
        yield pair


class TestRouting:
    """USER_STORAGE routes to the users client/bucket; PROVIDER_STORAGE to partners."""

    def test_user_storage_uses_users_client(self, s3_pair):
        users, partners = s3_pair
        users.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
        FleetsCOSClient().get_object_bytes("key", WorkingDir.USER_STORAGE)
        users.get_object.assert_called_once()
        partners.get_object.assert_not_called()

    def test_provider_storage_uses_partners_client(self, s3_pair):
        users, partners = s3_pair
        partners.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
        FleetsCOSClient().get_object_bytes("key", WorkingDir.PROVIDER_STORAGE)
        partners.get_object.assert_called_once()
        users.get_object.assert_not_called()

    def test_user_storage_uses_users_bucket(self, s3_pair):
        users, _ = s3_pair
        users.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
        FleetsCOSClient().get_object_bytes("key", WorkingDir.USER_STORAGE)
        assert users.get_object.call_args.kwargs["Bucket"] == settings.FLEETS_USERS_COS_BUCKET

    def test_provider_storage_uses_partners_bucket(self, s3_pair):
        _, partners = s3_pair
        partners.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
        FleetsCOSClient().get_object_bytes("key", WorkingDir.PROVIDER_STORAGE)
        assert partners.get_object.call_args.kwargs["Bucket"] == settings.FLEETS_PARTNERS_COS_BUCKET


class TestGetObjectBytes:
    def test_returns_none_on_no_such_key(self, s3_pair):
        users, _ = s3_pair
        users.get_object.side_effect = _client_error("NoSuchKey")
        assert FleetsCOSClient().get_object_bytes("key", WorkingDir.USER_STORAGE) is None

    def test_raises_cos_error_on_other_client_error(self, s3_pair):
        users, _ = s3_pair
        users.get_object.side_effect = _client_error("AccessDenied")
        with pytest.raises(COSError):
            FleetsCOSClient().get_object_bytes("key", WorkingDir.USER_STORAGE)


class TestGetObject:
    def test_decodes_bytes_to_str(self, s3_pair):
        users, _ = s3_pair
        users.get_object.return_value = {"Body": MagicMock(read=lambda: b"hello")}
        assert FleetsCOSClient().get_object("key", WorkingDir.USER_STORAGE) == "hello"

    def test_returns_none_when_key_not_found(self, s3_pair):
        users, _ = s3_pair
        users.get_object.side_effect = _client_error("NoSuchKey")
        assert FleetsCOSClient().get_object("key", WorkingDir.USER_STORAGE) is None


class TestPutObject:
    def test_encodes_str_to_utf8_bytes(self, s3_pair):
        users, _ = s3_pair
        FleetsCOSClient().put_object("key", "héllo", WorkingDir.USER_STORAGE)
        assert users.put_object.call_args.kwargs["Body"] == "héllo".encode("utf-8")


class TestDeleteObject:
    def test_returns_true_on_success(self, s3_pair):
        assert FleetsCOSClient().delete_object("key", WorkingDir.USER_STORAGE) is True

    def test_returns_false_on_client_error(self, s3_pair):
        users, _ = s3_pair
        users.delete_object.side_effect = _client_error("InternalError")
        assert FleetsCOSClient().delete_object("key", WorkingDir.USER_STORAGE) is False


class TestListObjects:
    def test_returns_keys_from_contents(self, s3_pair):
        users, _ = s3_pair
        users.list_objects_v2.return_value = {"Contents": [{"Key": "a/b.txt"}, {"Key": "a/c.txt"}]}
        assert FleetsCOSClient().list_objects("a/", WorkingDir.USER_STORAGE) == ["a/b.txt", "a/c.txt"]

    def test_returns_empty_list_when_no_contents(self, s3_pair):
        users, _ = s3_pair
        users.list_objects_v2.return_value = {}
        assert FleetsCOSClient().list_objects("a/", WorkingDir.USER_STORAGE) == []
