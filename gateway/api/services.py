"""
Services for api application:
    - Program Service
    - Job Service

Version services inherit from the different services.
"""

import logging

from .models import Program
from .exceptions import InternalServerErrorException

logger = logging.getLogger("services")


class ProgramService:
    @staticmethod
    def save(serializer, author, artifact) -> Program:
        title = serializer.data.get("title")
        existing_program = (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )

        if existing_program is not None:
            program = existing_program
            program.arguments = serializer.data.get("arguments")
            program.entrypoint = serializer.data.get("entrypoint")
            program.dependencies = serializer.data.get("dependencies", "[]")
            program.env_vars = serializer.data.get("env_vars", "{}")
        else:
            program = Program(**serializer.data)
        program.artifact = artifact
        program.author = author

        ## TODO: It would be nice if we could unify all the saves logic in one unique entry-point
        try:
            program.save()
        except (Exception) as save_program_exception:
            logger.error(
                "Exception was caught saving the program [%s] by [%s] \n"
                "Error trace: %s",
                title,
                author,
                save_program_exception,
            )
            raise InternalServerErrorException("Unexpected error saving the program")

        return program
