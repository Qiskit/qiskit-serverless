"""Download a file from user storage use case."""

# pylint: disable=duplicate-code
import logging
from django.contrib.auth.models import AbstractUser
from api.services.storage import FileStorage, WorkingDir
from api.repositories.functions import FunctionRepository
from api.domain.exceptions.not_found_error import NotFoundError

from api.models import RUN_PROGRAM_PERMISSION

logger = logging.getLogger("gateway.use_cases.files")


class FilesDownloadUseCase:
    """
    Download a file from user storage use case.
    """

    function_repository = FunctionRepository()
    working_dir = WorkingDir.USER_STORAGE

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        requested_file_name: str,
    ):
        """
        Download a file from user storage.
        """
        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )

        if not function:
            if provider_name:
                error_message = f"Qiskit Function {provider_name}/{function_title} doesn't exist."  # pylint: disable=line-too-long
            else:
                error_message = f"Qiskit Function {function_title} doesn't exist."
            raise NotFoundError(error_message)

        file_storage = FileStorage(
            username=user.username,
            working_dir=self.working_dir,
            function=function,
        )
        result = file_storage.get_file(file_name=requested_file_name)

        if result is None:
            raise NotFoundError("Requested file was not found.")

        return result
