"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import List
from api.services.file_storage import FileStorage, WorkingDir
from api.repositories.functions import FunctionRepository

from api.models import RUN_PROGRAM_PERMISSION


logger = logging.getLogger("gateway.use_cases.files")


class FilesListUseCase:
    """
    This class will return available dynamic dependencies on execute.
    """

    function_repository = FunctionRepository()

    def execute(self, user, provider_name, function_title) -> List[str]:
        """
        Get the dependencies from the whitlist
        """
        working_dir = WorkingDir.USER_STORAGE
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
            raise ValueError({"message": error_message})

        file_storage = FileStorage(
            username=user.username,
            working_dir=working_dir,
            function_title=function_title,
            provider_name=provider_name,
        )

        return file_storage.get_files()
