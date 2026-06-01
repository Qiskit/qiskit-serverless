"""Delete file from provider storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException

from api.repositories.providers import ProviderRepository
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program as Function
from core.services.storage import get_file_storage

logger = logging.getLogger("api.FilesProviderDeleteUseCase")


class FilesProviderDeleteUseCase:
    """
    Delete file from provider storage use case.
    """

    provider_repository = ProviderRepository()

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        file_name: str,
        *,
        accessible_functions: FunctionAccessResult,
    ):
        """
        Delete file from provider storage.
        """

        provider = self.provider_repository.get_provider_by_name(name=provider_name)
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
        result = file_storage.remove_private_file(file_name=file_name)

        if not result:
            raise FileNotFoundException()
