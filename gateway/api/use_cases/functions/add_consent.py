import logging
from django.contrib.auth.models import AbstractUser
from api.repositories.functions import FunctionRepository
from api.v1.endpoint_handle_exceptions import NotFoundError

logger = logging.getLogger("gateway.use_cases.functions")


class AddLogConsentUseCase:

    function_repository = FunctionRepository()

    def execute(self, user: AbstractUser, function_title: str, accepted: bool):
        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name="RUN_PROGRAM_PERMISSION",
            function_title=function_title,
        )
        if function is None:
            raise NotFoundError(f"Function [{function_title}] not found")

        self.function_repository.add_log_consent_to_function(
            user=user, function=function, accepted=accepted
        )
