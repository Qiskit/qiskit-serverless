"""Use cases: upload a custom Fleets function's files straight to COS with presigned URLs."""

import logging

from django.contrib.auth.models import AbstractUser
from ibm_botocore.exceptions import BotoCoreError, ClientError

from api.access_policies.programs import ProgramAccessPolicies
from api.domain.exceptions.artifact_too_large_error import ArtifactTooLargeError
from api.domain.exceptions.custom_function_not_entitled_exception import CustomFunctionNotEntitledException
from api.domain.exceptions.engine_unavailable_exception import EngineUnavailableException
from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.use_cases.programs.upload import UploadFunctionUseCase, no_ce_project_message
from api.use_cases.programs.upload_input import UploadFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import CodeEngineProject, Program as Function
from core.services.storage.file_storage_fleets import FileStorageFleets

logger = logging.getLogger("api.use_cases.programs.presigned_upload")

UPLOAD_URL_SECONDS = 300
MAX_FILES = 1000
MAX_SIZE_MB = 50


def _fleets_function(user: AbstractUser, accessible_functions: FunctionAccessResult, title: str) -> Function:
    """The user's custom function as Fleets, with its Code Engine project, new and unsaved when it does not exist."""
    if not ProgramAccessPolicies.can_create(user, accessible_functions):
        raise CustomFunctionNotEntitledException(title=title, operation=CustomFunctionNotEntitledException.UPLOAD)
    function = Function.objects.filter(title=title, author=user).first() or Function(title=title, author=user)
    function.runner = Function.FLEETS
    CodeEngineProject.objects.assign_to_program(function)
    if not function.code_engine_project:
        raise FunctionConfigurationException(no_ce_project_message(function))
    return function


def _check_files(files: dict[str, int], entrypoint: str) -> None:
    """Raise when a path would leave the data folder, the entrypoint is missing, or the files are too large."""
    if len(files) > MAX_FILES:
        raise FunctionConfigurationException(f"At most {MAX_FILES} files can be uploaded.")
    for path in files:
        parts = path.split("/")
        if not all(parts) or "." in parts or ".." in parts or any(ord(c) < 32 for c in path):
            raise FunctionConfigurationException(f"File path '{path}' is not allowed.")
    if entrypoint not in files:
        raise FunctionConfigurationException(f"Entrypoint file '{entrypoint}' is not in the files.")
    total = sum(files.values())
    if total > MAX_SIZE_MB * 1024**2:
        raise ArtifactTooLargeError(total, MAX_SIZE_MB)


class StartUploadUseCase:
    """Check the user may upload the function, and give it a URL to PUT each file to."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        *,
        title: str,
        entrypoint: str,
        files: dict[str, int],
    ) -> dict[str, str]:
        """The PUT URL of each file path. Clears the old tar of the function."""
        _check_files(files, entrypoint)
        function = _fleets_function(user, accessible_functions, title)
        urls = FileStorageFleets(user.username, function).presigned_public_put_urls(files, UPLOAD_URL_SECONDS)
        if function.artifact:
            function.artifact = ""
            function.save(update_fields=["artifact"])
        logger.info("user_id=%s program=%s files=%s | Upload started", user.id, title, len(files))
        return urls


class FinishUploadUseCase:
    """Save the function, after the client PUT its files to COS."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        data: UploadFunctionInput,
        files: dict[str, int],
    ) -> Function:
        """The saved function. Raises when a file of ``start`` is not in COS with its size."""
        _check_files(files, data.entrypoint)
        function = _fleets_function(user, accessible_functions, data.title)
        try:
            uploaded = FileStorageFleets(user.username, function).public_file_sizes()
        except (ClientError, BotoCoreError) as ex:
            logger.warning("user_id=%s program=%s | Files not checked in COS: %s", user.id, data.title, ex)
            raise EngineUnavailableException("The upload could not be finished right now, please retry.") from ex
        missing = sorted(path for path, size in files.items() if uploaded.get(path) != size)
        if missing:
            raise FunctionConfigurationException(
                f"{len(missing)} files were not uploaded, for example {missing[:3]}, upload the function again."
            )

        data.artifact = ""
        data.runner = Function.FLEETS
        return UploadFunctionUseCase().execute(user, accessible_functions, data)
