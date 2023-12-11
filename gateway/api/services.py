"""
Services for api application:
    - Program Service
    - Job Service

Version services inherit from the different services.
"""

# pylint: disable=too-few-public-methods

import logging

from .models import Program, JobConfig
from .exceptions import InternalServerErrorException, ResourceNotFoundException

logger = logging.getLogger("gateway.services")


class ProgramService:
    """
    Program service allocate the logic related with programs
    """

    @staticmethod
    def save(serializer, author, artifact) -> Program:
        """
        Save method gets a program serializer and creates or updates a program
        """

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
            logger.debug("Program [%s] will be updated by [%s]", title, author)
        else:
            program = Program(**serializer.data)
            logger.debug("Program [%s] will be created by [%s]", title, author)
        program.artifact = artifact
        program.author = author

        # It would be nice if we could unify all the saves logic in one unique entry-point
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
            raise InternalServerErrorException(
                "Unexpected error saving the program"
            ) from save_program_exception

        logger.debug("Program [%s] saved", title)

        return program

    @staticmethod
    def find_one_by_title(title, author) -> Program:
        """
        It returns the last created Program by title from an author
        """

        logger.debug("Filtering Program by title[%s] and author [%s]", title, author)
        program = (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )

        if program is None:
            logger.error("Program [%s] by author [%s] not found", title, author)
            raise ResourceNotFoundException("Program [{title}] was not found")

        return program


class JobConfigService:
    """
    JobConfig service allocate the logic related with job configuration
    """

    @staticmethod
    def save_with_serializer(serializer) -> JobConfig:
        """
        This
        """

        # It would be nice if we could unify all the saves logic in one unique entry-point
        try:
            jobconfig = serializer.save()
        except (Exception) as save_job_config_exception:
            logger.error(
                "Exception was caught saving a JobConfig. \n Error trace: %s",
                save_job_config_exception,
            )
            raise InternalServerErrorException(
                "Unexpected error saving the configuration of the job"
            ) from save_job_config_exception

        logger.debug("JobConfig [%s] saved", jobconfig.id)

        return jobconfig
