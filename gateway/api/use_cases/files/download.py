"""Download a file from user storage use case."""

# pylint: disable=duplicate-code
import logging
from typing import Iterator, Tuple

from django.contrib.auth.models import AbstractUser

from api.access_policies.programs import ProgramAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program as Function
from core.services.storage import get_file_storage

logger = logging.getLogger("api.FilesDownloadUseCase")


class FilesDownloadUseCase:
    """
    Download a file from user storage use case.
    """

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        requested_file_name: str,
        *,
        accessible_functions: FunctionAccessResult,
    ) -> Tuple[Iterator[bytes], str, int]:
        """
        Download a file from user storage.
        """
        if provider_name:
            function = Function.objects.get_function(function_title, provider_name)
            if function and not ProgramAccessPolicies.can_read_user_files(user, function, accessible_functions):
                function = None
        else:
            function = Function.objects.get_user_function(user, function_title)

        if not function:
            raise FunctionNotFoundException(function=function_title)

        file_storage = get_file_storage(
            username=user.username,
            function=function,
        )
        result = file_storage.get_public_file_stream(file_name=requested_file_name)

        if result is None:
            raise FileNotFoundException()

        return result
