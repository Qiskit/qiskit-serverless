"""Use case: retrieve jobs for a Qiskit Function."""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db.models import QuerySet

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job
from core.models import Program as Function


class GetJobsUseCase:
    """Use case for listing jobs belonging to a Qiskit Function."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        program_id: uuid.UUID,
    ) -> QuerySet:
        """Return jobs for the given program, filtered by access level.

        Provider admins see all jobs for their function; regular users see only their own.
        Raises FunctionNotFoundException if the program does not exist.
        """
        program = Function.objects.filter(id=program_id).first()
        if program is None:
            raise FunctionNotFoundException(function=str(program_id))

        if program.provider and ProviderAccessPolicy.can_list_jobs(
            user=user,
            provider=program.provider,
            function_title=program.title,
            accessible_functions=accessible_functions,
        ):
            return Job.objects.filter(program=program)

        return Job.objects.filter(program=program, author=user)
