"""Authentication use case to manage the authentication process in the api."""
# pylint: disable=duplicate-code
import logging
from typing import List
from django.contrib.auth.models import AbstractBaseUser
from api.services.file_storage import FileStorage, WorkingDir
from api.repositories.functions import FunctionRepository
from api.domain.exceptions.not_found_error import NotFoundError

from api.models import RUN_PROGRAM_PERMISSION


logger = logging.getLogger("gateway.use_cases.files")


class FilesDeleteUseCase:
    """
    This class will return the files in the user storage.
    """

    function_repository = FunctionRepository()
    working_dir = WorkingDir.USER_STORAGE

    def execute(
        self,
        user: AbstractBaseUser,
        provider_name: str,
        function_title: str,
        file_name: str,
    ) -> List[str]:
        """
        Get the files from the user storage
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
            function_title=function_title,
            provider_name=provider_name,
        )
        result = file_storage.remove_file(file_name=file_name)

        if not result:
            raise NotFoundError("Requested file was not found.")

        return result
