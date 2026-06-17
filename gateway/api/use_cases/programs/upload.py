"""Use case: upload (create or update) a Qiskit Function."""

from django.contrib.auth.models import AbstractUser

from api.access_policies.programs import ProgramAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.v1.serializers import UploadProgramSerializer
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program as Function, Provider


class UploadFunctionUseCase:
    """Use case for uploading (creating or updating) a Qiskit Function."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        request_data: dict,
    ) -> Function:
        """Create or update a Qiskit Function.

        Validates the request data, checks permissions, and saves the function.
        Raises FunctionNotFoundException when the user lacks permission.
        """
        serializer = UploadProgramSerializer(data=request_data)
        serializer.is_valid(raise_exception=True)

        title_raw = serializer.validated_data.get("title")
        provider_raw = serializer.validated_data.get("provider", None)
        provider_name, title = serializer.get_provider_name_and_title(provider_raw, title_raw)

        if provider_name:
            provider = Provider.objects.filter(name=provider_name).first()
            if provider is None or not ProviderAccessPolicy.can_upload_function(
                user, provider, title, accessible_functions
            ):
                raise FunctionNotFoundException(function=title, provider=provider_name)
            existing = Function.objects.filter(title=title, provider__name=provider_name).first()
        else:
            if not ProgramAccessPolicies.can_create(user, accessible_functions):
                raise FunctionNotFoundException(function=title, provider=None)
            existing = Function.objects.filter(title=title, author=user).first()

        if existing is not None:
            serializer = UploadProgramSerializer(existing, data=request_data)
            serializer.is_valid(raise_exception=True)

        runner = serializer.validated_data.get("runner", Function.RAY)
        serializer.save(author=user, title=title, provider=provider_name, runner=runner)

        return serializer.instance
