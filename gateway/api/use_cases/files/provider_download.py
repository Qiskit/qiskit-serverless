"""Download a file from provider storage use case."""
# pylint: disable=duplicate-code
import logging
from django.contrib.auth.models import AbstractBaseUser
from api.access_policies.providers import ProviderAccessPolicy
from api.repositories.providers import ProviderRepository
from api.services.file_storage import FileStorage, WorkingDir
from api.repositories.functions import FunctionRepository
from api.domain.exceptions.not_found_error import NotFoundError

from api.models import RUN_PROGRAM_PERMISSION

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
        user: AbstractBaseUser,
        provider_name: str,
        function_title: str,
        requested_file_name: str,
    ):
        """
        Download a file from provider storage.
        """

        provider = self.provider_repository.get_provider_by_name(name=provider_name)
        if provider is None or not ProviderAccessPolicy.can_access(
            user=user, provider=provider
        ):
            raise NotFoundError(f"Provider {provider_name} doesn't exist.")

        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )

        if not function:
            raise NotFoundError(
                f"Qiskit Function {provider_name}/{function_title} doesn't exist."
            )

        file_storage = FileStorage(
            username=user.username,
            working_dir=self.working_dir,
            function_title=function_title,
            provider_name=provider_name,
        )
        result = file_storage.get_file(file_name=requested_file_name)

        if result is None:
            raise NotFoundError("Requested file was not found.")

        return result
