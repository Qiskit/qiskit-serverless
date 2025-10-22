"""This module contains the usecase get_jos"""
from dataclasses import dataclass
import logging
from typing import Optional

from django.contrib.auth.models import AbstractUser
from rest_framework import serializers
from rest_framework.utils.serializer_helpers import ReturnDict

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.bad_request import BadRequest
from api.domain.exceptions.not_found_error import NotFoundError
from api.models import Program
from api.repositories.functions import FunctionRepository
from api.repositories.providers import ProviderRepository

logger = logging.getLogger("gateway.use_cases.functions.upload")


@dataclass(slots=True)
class UploadFunctionData:
    """
    Filters for Job queries.
    """

    function_title: str = None
    provider: Optional[str] = None

    entrypoint: Optional[str] = None
    image: Optional[str] = None

    arguments: Optional[str] = None
    dependencies: Optional[str] = None
    env_vars: Optional[str] = None
    description: Optional[str] = None


class ProgramSerializer(serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point
    """

    class Meta:
        model = Program


class FunctionUploadUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    provider_repository = ProviderRepository()
    function_repository = FunctionRepository()

    def execute(self, author: AbstractUser, data: UploadFunctionData) -> ReturnDict:
        """
        Retrieve user jobs with optional filters and pagination.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)
        """
        provider_name = data.provider
        if provider_name:
            provider = self.provider_repository.get_provider_by_name(provider_name)
            if provider is None:
                raise NotFoundError(f"Provider [{provider_name}] was not found.")

            user_has_access = ProviderAccessPolicy.can_access(
                user=author, provider=provider
            )
            if not user_has_access:
                # For security we just return a 404 not a 401
                raise NotFoundError(f"Provider [{provider_name}] was not found.")
            program = self.function_repository.get_function(
                function_title=data.function_title, provider_name=provider_name
            )
        else:
            program = self.function_repository.get_user_function(
                author=author, title=data.function_title
            )

        if program is None:
            serializer: ProgramSerializer = ProgramSerializer(data=data)
        else:
            logger.info("Program found. [%s] is going to be updated", program.title)
            serializer: ProgramSerializer = ProgramSerializer(program, data=data)

        if not serializer.is_valid():
            logger.error(
                "UploadProgramSerializer validation failed with program instance:\n %s",
                serializer.errors,
            )
            raise BadRequest(serializer.errors)

        serializer.save(
            author=author, title=data.function_title, provider=provider_name
        )

        return serializer.data
