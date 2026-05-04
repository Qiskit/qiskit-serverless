"""Download a file from user storage use case."""

# pylint: disable=duplicate-code
import logging
from typing import Iterator, Tuple

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException

from core.models import RUN_PROGRAM_PERMISSION
from core.services.storage.file_storage import FileStorage, WorkingDir
from core.models import Program as Function

logger = logging.getLogger("api.FilesDownloadUseCase")


class FilesDownloadUseCase:
    """
    Download a file from user storage use case.
    """

    working_dir = WorkingDir.USER_STORAGE

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        requested_file_name: str,
    ) -> Tuple[Iterator[bytes], str, int]:
        """
        Download a file from user storage.
        """
        function = Function.objects.get_function_by_permission(
            user=user,
            legacy_permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )

        if not function:
            raise FunctionNotFoundException(function=function_title)

        file_storage = FileStorage(
            username=user.username,
            working_dir=self.working_dir,
            function=function,
        )
        result = file_storage.get_file_stream(file_name=requested_file_name)

        if result is None:
            raise FileNotFoundException()

        return result
