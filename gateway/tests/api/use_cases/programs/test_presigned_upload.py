"""Unit tests for the upload straight to COS: StartUploadUseCase and FinishUploadUseCase."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from ibm_botocore.exceptions import ClientError

from api.domain.exceptions.artifact_too_large_error import ArtifactTooLargeError
from api.domain.exceptions.engine_unavailable_exception import EngineUnavailableException
from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.use_cases.programs.presigned_upload import (
    MAX_FILES,
    MAX_SIZE_MB,
    FinishUploadUseCase,
    StartUploadUseCase,
)
from api.use_cases.programs.upload_input import UploadFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("default_ce_project")]

_COS = "core.services.storage.file_storage_fleets.get_cos_client"
ACCESSIBLE = FunctionAccessResult(use_legacy_authorization=True, functions=[])


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def cos():
    client = MagicMock()
    client.get_presigned_put_url.side_effect = lambda **kw: f"https://cos/{kw['key']}?size={kw['size']}"
    client.list_with_metadata.return_value = [{"key": "users/author/custom_functions/my-fn/data/main.py", "size": 10}]
    with patch(_COS, return_value=client):
        yield client


def _start(user, files=None):
    return StartUploadUseCase().execute(
        user, ACCESSIBLE, title="my-fn", entrypoint="main.py", files=files or {"main.py": 10}
    )


def _finish(user, files=None):
    return FinishUploadUseCase().execute(
        user, ACCESSIBLE, UploadFunctionInput(title="my-fn", entrypoint="main.py"), files or {"main.py": 10}
    )


def test_start_gives_a_put_url_per_file_in_the_data_folder_and_saves_nothing(user, cos):
    urls = _start(user, {"main.py": 10, "pkg/util.py": 20})

    prefix = "https://cos/users/author/custom_functions/my-fn/data"
    assert urls == {"main.py": f"{prefix}/main.py?size=10", "pkg/util.py": f"{prefix}/pkg/util.py?size=20"}
    assert not Program.objects.filter(title="my-fn").exists()


@pytest.mark.parametrize("path", ["../other-fn/main.py", "/etc/passwd", "pkg/./util.py", "pkg//util.py"])
def test_start_refuses_a_path_outside_the_data_folder(user, cos, path):
    with pytest.raises(FunctionConfigurationException, match="not allowed"):
        _start(user, {"main.py": 10, path: 10})
    cos.get_presigned_put_url.assert_not_called()


def test_start_refuses_files_without_the_entrypoint(user, cos):
    with pytest.raises(FunctionConfigurationException, match="Entrypoint"):
        _start(user, {"other.py": 10})


def test_start_refuses_too_many_files(user, cos):
    files = {"main.py": 1} | {f"f{i}.py": 1 for i in range(MAX_FILES)}
    with pytest.raises(FunctionConfigurationException, match="At most"):
        _start(user, files)


def test_start_refuses_files_over_the_limit(user, cos):
    with pytest.raises(ArtifactTooLargeError):
        _start(user, {"main.py": MAX_SIZE_MB * 1024**2, "data.bin": 1})
    cos.get_presigned_put_url.assert_not_called()


def test_upload_moves_a_ray_function_to_fleets(user, cos):
    Program.objects.create(title="my-fn", author=user, runner=Program.RAY)

    _start(user)
    function = _finish(user)

    assert Program.objects.get(pk=function.pk).runner == Program.FLEETS


def test_start_accepts_names_the_tar_accepted(user, cos):
    urls = _start(user, {"main.py": 10, "my notebook.ipynb": 1, "data (1).csv": 1, "café.py": 1})

    assert len(urls) == 4


def test_finish_saves_a_fleets_function_without_a_tar(user, cos):
    function = _finish(user)

    assert function.runner == Program.FLEETS
    assert not function.artifact
    assert cos.list_with_metadata.call_args.kwargs["prefix"] == "users/author/custom_functions/my-fn/data/"


def test_finish_checks_files_in_sub_folders_and_ignores_other_files(user, cos):
    cos.list_with_metadata.return_value = [
        {"key": "users/author/custom_functions/my-fn/data/main.py", "size": 10},
        {"key": "users/author/custom_functions/my-fn/data/pkg/util.py", "size": 20},
        {"key": "users/author/custom_functions/my-fn/data/data.csv", "size": 99},
    ]

    assert _finish(user, {"main.py": 10, "pkg/util.py": 20}).runner == Program.FLEETS


def test_start_clears_the_tar_of_an_earlier_upload(user, cos):
    function = Program.objects.create(
        title="my-fn", author=user, runner=Program.FLEETS, artifact=ContentFile(b"tar", name="old.tar")
    )

    _start(user)

    assert not Program.objects.get(pk=function.pk).artifact


def test_finish_clears_the_tar_without_a_start(user, cos):
    function = Program.objects.create(
        title="my-fn", author=user, runner=Program.FLEETS, artifact=ContentFile(b"tar", name="old.tar")
    )

    _finish(user)

    assert not Program.objects.get(pk=function.pk).artifact


@pytest.mark.parametrize("files", [{"main.py": 10, "util.py": 5}, {"main.py": 11}])
def test_finish_refuses_a_file_that_is_missing_or_has_another_size(user, cos, files):
    with pytest.raises(FunctionConfigurationException, match="were not uploaded"):
        _finish(user, files)
    assert not Program.objects.filter(title="my-fn").exists()


def test_finish_answers_unavailable_when_cos_fails(user, cos):
    cos.list_with_metadata.side_effect = ClientError({"Error": {"Code": "503", "Message": ""}}, "ListObjectsV2")

    with pytest.raises(EngineUnavailableException):
        _finish(user)


def test_start_refuses_when_there_is_no_active_project(user, cos, default_ce_project):
    default_ce_project.active = False
    default_ce_project.save(update_fields=["active", "updated"])

    with pytest.raises(FunctionConfigurationException, match="Code Engine project"):
        _start(user)
