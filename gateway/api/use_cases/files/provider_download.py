"""Download a file from provider storage use case."""

# pylint: disable=duplicate-code
import logging

from django.contrib.auth.models import AbstractUser

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.file_not_found_exception import FileNotFoundException
from api.repositories.functions import FunctionRepository
from api.repositories.providers import ProviderRepository
from core.models import RUN_PROGRAM_PERMISSION
from core.services.storage.file_storage import FileStorage, WorkingDir

logger = logging.getLogger("gateway.use_cases.files")


class FilesProviderDownloadUseCase:
    """
    Download a file from provider storage use case.
    """

    function_repository = FunctionRepository()
    provider_repository = ProviderRepository()
    working_dir = WorkingDir.PROVIDER_STORAGE

    def execute(
        self,
        user: AbstractUser,
        provider_name: str,
        function_title: str,
        requested_file_name: str,
    ):
        """
        Download a file from provider storage.
        """

        provider = self.provider_repository.get_provider_by_name(name=provider_name)
        if provider is None or not ProviderAccessPolicy.can_access(user=user, provider=provider):
            raise ProviderNotFoundException(provider_name)

        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )

        if not function:
            raise FunctionNotFoundException(function=function_title, provider=provider_name)

        file_storage = FileStorage(
            username=user.username,
            working_dir=self.working_dir,
            function=function,
        )
        result = file_storage.get_file(file_name=requested_file_name)

        if result is None:
            raise FileNotFoundException()

        return result
