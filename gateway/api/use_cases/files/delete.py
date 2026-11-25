"""Delete file from user storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser

from api.access_policies.programs import ProgramAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException

from core.domain.authorization.function_access_result import FunctionAccessResult
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
        if provider_name:
            function = Function.objects.get_function(function_title, provider_name)
            if function and not ProgramAccessPolicies.can_write_user_files(user, function, accessible_functions):
                function = None
        else:
            function = Function.objects.get_user_function(user, function_title)

        if not function:
            raise FunctionNotFoundException(function=function_title)

        file_storage = get_file_storage(
            username=user.username,
            function=function,
        )
        result = file_storage.remove_public_file(file_name=file_name, sub_path=sub_path)

        if not result:
            raise FileNotFoundException()
