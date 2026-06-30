"""Upload a file into the provider storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser
from django.core.files import File

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program as Function, Provider
from core.services.storage import get_file_storage

logger = logging.getLogger("api.FilesProviderUploadUseCase")


class FilesProviderUploadUseCase:
    """
    Upload a file into the provider storage use case.
    """

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

        provider = Provider.objects.get_by_name(provider_name)
        if provider is None or not ProviderAccessPolicy.can_write_files(
            user=user,
            provider=provider,
            function_title=function_title,
            accessible_functions=accessible_functions,
        ):
            raise ProviderNotFoundException(provider_name)

        function = Function.objects.get_function(
            function_title=function_title,
            provider_name=provider_name,
        )

        if not function:
            raise FunctionNotFoundException(function=function_title, provider=provider_name)

        file_storage = get_file_storage(
            username=user.username,
            function=function,
        )
        result = file_storage.upload_private_file(file=uploaded_file)

        return result
