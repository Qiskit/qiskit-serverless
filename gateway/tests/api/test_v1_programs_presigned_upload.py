"""API tests of /programs/upload/start and /programs/upload/finish."""

import io
import json
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from api.use_cases.programs.presigned_upload import MAX_SIZE_MB
from core.models import Program
from core.services.runners.fleets_runner import FleetsRunner
from tests.utils import TestUtils

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("default_ce_project")]

_COS = "core.services.storage.file_storage_fleets.get_cos_client"


@pytest.fixture
def cos():
    client = MagicMock()
    uploaded = []

    def sign(**kw):
        uploaded.append({"key": kw["key"], "size": kw["size"]})
        return f"https://cos/{kw['key']}"

    client.get_presigned_put_url.side_effect = sign
    client.list_with_metadata.return_value = uploaded
    with patch(_COS, return_value=client):
        yield client


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def client(user):
    api = APIClient()
    TestUtils.authorize_client(user=user, client=api)
    return api


def _start(client, title, files):
    return client.post(
        "/api/v1/programs/upload/start/",
        data={"title": title, "entrypoint": "main.py", "files": files},
        format="json",
    )


def _finish(client, files, **fields):
    return client.post(
        "/api/v1/programs/upload/finish/",
        data={"title": "my-fn", "entrypoint": "main.py", "files": json.dumps(files), **fields},
        format="multipart",
    )


def test_start_then_finish_saves_a_fleets_function(client, cos):
    start = _start(client, "my-fn", [{"path": "main.py", "size": 10}, {"path": "pkg/util.py", "size": 20}])
    assert start.status_code == status.HTTP_200_OK
    assert start.data["urls"] == {
        "main.py": "https://cos/users/author/custom_functions/my-fn/data/main.py",
        "pkg/util.py": "https://cos/users/author/custom_functions/my-fn/data/pkg/util.py",
    }

    finish = _finish(client, [{"path": "main.py", "size": 10}, {"path": "pkg/util.py", "size": 20}])

    assert finish.status_code == status.HTTP_200_OK
    function = Program.objects.get(title="my-fn")
    assert function.runner == Program.FLEETS
    assert not function.artifact


def test_start_answers_413_for_files_over_the_limit(client, cos):
    start = _start(client, "my-fn", [{"path": "main.py", "size": MAX_SIZE_MB * 1024**2 + 1}])

    assert start.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


def test_start_refuses_a_provider_function(client, cos):
    start = _start(client, "acme/pfunc", [{"path": "main.py", "size": 10}])

    assert start.status_code == status.HTTP_400_BAD_REQUEST
    cos.get_presigned_put_url.assert_not_called()


def test_finish_ignores_an_image(client, cos):
    _start(client, "my-fn", [{"path": "main.py", "size": 10}])

    finish = _finish(client, [{"path": "main.py", "size": 10}], image="icr.io/acme/img:1")

    assert finish.status_code == status.HTTP_200_OK
    assert not Program.objects.get(title="my-fn").image


def _tar(files: dict[str, bytes]) -> SimpleUploadedFile:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return SimpleUploadedFile("artifact.tar", buf.getvalue())


def _old_upload(client, files):
    return client.post(
        "/api/v1/programs/upload/",
        data={"title": "my-fn", "entrypoint": "main.py", "artifact": _tar(files)},
        format="multipart",
    )


def _submit(user) -> list[str]:
    """Submit a job of my-fn with a real runner, and return the keys it wrote to COS."""
    job = TestUtils.create_job(author=user, program=Program.objects.get(title="my-fn"), runner=Program.FLEETS)
    runner = FleetsRunner(job)
    runner._handler = MagicMock()  # pylint: disable=protected-access
    runner._handler.submit_job.return_value = MagicMock(id="fleet-1")  # pylint: disable=protected-access
    with patch("core.services.runners.fleets_runner.get_cos_client") as cos:
        runner.submit()
    return [call.kwargs["key"] for call in cos.return_value.upload_fileobj.call_args_list]


_DATA = "users/author/custom_functions/my-fn/data"


def test_old_sdk_tar_upload_is_copied_at_submit(client, cos, user):
    assert _old_upload(client, {"main.py": b"print(1)", "pkg/util.py": b"x = 1"}).status_code == status.HTTP_200_OK

    assert _submit(user) == [f"{_DATA}/fleet_custom_job_wrapper.py", f"{_DATA}/main.py", f"{_DATA}/pkg/util.py"]


def test_presigned_upload_writes_only_the_wrapper_at_submit(client, cos, user):
    _start(client, "my-fn", [{"path": "main.py", "size": 8}])
    _finish(client, [{"path": "main.py", "size": 8}])

    assert _submit(user) == [f"{_DATA}/fleet_custom_job_wrapper.py"]


def test_presigned_upload_over_an_old_tar_stops_copying_the_tar(client, cos, user):
    _old_upload(client, {"main.py": b"old"})
    _start(client, "my-fn", [{"path": "main.py", "size": 3}])
    _finish(client, [{"path": "main.py", "size": 3}])

    assert _submit(user) == [f"{_DATA}/fleet_custom_job_wrapper.py"]
