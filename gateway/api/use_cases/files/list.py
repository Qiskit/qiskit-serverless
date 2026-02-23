"""List all files on user storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.repositories.functions import FunctionRepository
from core.models import RUN_PROGRAM_PERMISSION
from core.services.storage.file_storage import FileStorage, WorkingDir

logger = logging.getLogger("gateway.use_cases.files")


class FilesListUseCase:
    """
    List all files on user storage use case.
    """

    function_repository = FunctionRepository()
    working_dir = WorkingDir.USER_STORAGE

    def execute(self, user: AbstractUser, provider_name: str, function_title: str):
        """
        List all files on user storage.
        """
        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name=RUN_PROGRAM_PERMISSION,
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

        return file_storage.get_files()
