"""Root conftest for gateway tests.

Provides a FakeCOSClient and an autouse fixture that patches every
get_cos / get_cos_for_program call site so that no test accidentally
makes real network requests to an S3/COS endpoint.
"""

from unittest.mock import patch as mock_patch

import pytest

from core.services.storage.enums.working_dir import WorkingDir


class FakeCOSClient:
    """In-memory COS client for unit tests."""

    def __init__(self):
        self._store: dict[tuple, bytes] = {}

    def get_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE):
        data = self._store.get((key, working_dir))
        return data.decode("utf-8") if data is not None else None

    def put_object(self, key: str, content: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE):
        self._store[(key, working_dir)] = content.encode("utf-8")

    def get_object_bytes(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE):
        return self._store.get((key, working_dir))

    def put_object_bytes(self, key: str, content: bytes, working_dir: WorkingDir = WorkingDir.USER_STORAGE):
        self._store[(key, working_dir)] = content

    def delete_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> bool:
        return self._store.pop((key, working_dir), None) is not None

    def list_objects(self, prefix: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> list[str]:
        return [k for (k, wd) in self._store.keys() if k.startswith(prefix) and wd == working_dir]


_COS_TARGETS = [
    "core.services.storage.logs_storage.get_cos",
    "core.services.storage.result_storage.get_cos",
    "core.services.storage.arguments_storage.get_cos",
    "core.services.runners.ray_runner.get_cos",
    "api.use_cases.files.upload.get_cos_for_program",
    "api.use_cases.files.download.get_cos_for_program",
    "api.use_cases.files.list.get_cos_for_program",
    "api.use_cases.files.delete.get_cos_for_program",
    "api.use_cases.files.provider_upload.get_cos_for_program",
    "api.use_cases.files.provider_download.get_cos_for_program",
    "api.use_cases.files.provider_list.get_cos_for_program",
    "api.use_cases.files.provider_delete.get_cos_for_program",
]


@pytest.fixture
def fake_cos():
    return FakeCOSClient()


@pytest.fixture(autouse=True)
def mock_cos(fake_cos):
    """Patch every COS call site to use an in-memory FakeCOSClient.

    Returned so individual tests can pre-populate or inspect COS state.
    """
    patches = [mock_patch(t, new=lambda *_: fake_cos) for t in _COS_TARGETS]
    for p in patches:
        p.start()
    yield fake_cos
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def media_root_tmp(tmp_path, settings):
    """Redirect MEDIA_ROOT to a temp directory for every test.

    Prevents PathBuilder.absolute_path() from creating directories inside
    the source tree (gateway/media/) during test runs.
    """
    settings.MEDIA_ROOT = str(tmp_path)
