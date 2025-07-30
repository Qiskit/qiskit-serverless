"""Authentication use case to manage the authentication process in the api."""
# pylint: disable=duplicate-code
import logging
from typing import List
from api.access_policies.providers import ProviderAccessPolicy
from api.repositories.providers import ProviderRepository
from api.services.file_storage import FileStorage, WorkingDir
from api.repositories.functions import FunctionRepository
from api.domain.exceptions.not_found_error import NotFoundError

from api.models import RUN_PROGRAM_PERMISSION


logger = logging.getLogger("gateway.use_cases.files")


class FilesProviderUploadUseCase:
    """
    This class will return available dynamic dependencies on execute.
    """

    function_repository = FunctionRepository()
    provider_repository = ProviderRepository()
    working_dir = WorkingDir.PROVIDER_STORAGE

    def execute(self, user, provider_name, function_title, uploaded_file) -> List[str]:
        """
        Get the dependencies from the whitlist
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
        result = file_storage.upload_file(file=uploaded_file)

        return result
