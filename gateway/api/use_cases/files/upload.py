"""Upload a file into the provider storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser
from django.core.files import File

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_USER_FILES_WRITE, RUN_PROGRAM_PERMISSION
from core.models import Program as Function
from core.services.storage.file_storage import FileStorage, WorkingDir

logger = logging.getLogger("api.FilesUploadUseCase")


class FilesUploadUseCase:
    """
    Upload a file into the provider storage use case.
    """

    working_dir = WorkingDir.USER_STORAGE

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        uploaded_file: File,
        *,
        accessible_functions: FunctionAccessResult,
    ):
        """
        Upload a file into the provider storage.
        """
        function = Function.objects.get_function_by_permission(
            user=user,
            function_title=function_title,
            provider_name=provider_name,
            accessible_functions=accessible_functions,
            permission=PLATFORM_PERMISSION_USER_FILES_WRITE,
            legacy_permission_name=RUN_PROGRAM_PERMISSION,
        )

        if not function:
            raise FunctionNotFoundException(function=function_title)

        file_storage = FileStorage(
            username=user.username,
            working_dir=self.working_dir,
            function=function,
        )
        result = file_storage.upload_file(file=uploaded_file)

        return result
