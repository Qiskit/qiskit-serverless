"""Delete file from user storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_USER_FILES_WRITE, RUN_PROGRAM_PERMISSION
from core.models import Program as Function
from core.services.storage import get_file_storage

logger = logging.getLogger("api.FilesDeleteUseCase")


class FilesDeleteUseCase:
    """
    Delete file from user storage use case.
    """

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        file_name: str,
        *,
        sub_path: str = "",
        accessible_functions: FunctionAccessResult,
    ):
        """
        Delete file from user storage.

        ``sub_path`` is an optional, already-sanitized relative directory under the user's
        public file folder (e.g. ``"wheels"``).
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

        file_storage = get_file_storage(
            username=user.username,
            function=function,
        )
        result = file_storage.remove_public_file(file_name=file_name, sub_path=sub_path)

        if not result:
            raise FileNotFoundException()
