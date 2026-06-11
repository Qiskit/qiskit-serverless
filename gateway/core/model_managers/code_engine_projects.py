# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Code Engine project model manager."""

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import CodeEngineProject, Program

logger = logging.getLogger("core.model_managers.code_engine_projects")


class CodeEngineProjectQuerySet(QuerySet):
    """QuerySet for CodeEngineProject with selection and assignment helpers."""

    def select_default(self) -> "CodeEngineProject | None":
        """Select the default active Code Engine project.

        Requires ``settings.CE_DEFAULT_PROJECT_NAME`` to be configured.

        Returns:
            Active CodeEngineProject, or None if no matching project is found.

        Raises:
            ValueError: If CE_DEFAULT_PROJECT_NAME is not configured.
        """
        default_name: str = settings.CE_DEFAULT_PROJECT_NAME
        if not default_name:
            raise ValueError("CE_DEFAULT_PROJECT_NAME not configured")

        project = self.filter(active=True, project_name=default_name).first()
        if not project:
            logger.warning(
                "CE_DEFAULT_PROJECT_NAME='%s' does not match any active project",
                default_name,
            )
        return project

    def assign_to_program(self, program: "Program") -> None:
        """Assign a CodeEngineProject to a Fleets program that lacks one.

        No-op if the program already has a CE project or is not a Fleets runner.
        Mutates ``program.code_engine_project`` in place — caller must save.

        Args:
            program: Program instance to check and potentially assign a project to.
        """
        if program.runner != program.FLEETS:
            return
        if program.code_engine_project:
            return

        program.code_engine_project = self.select_default()
        if not program.code_engine_project:
            logger.warning(
                "program='%s' | No active CodeEngineProject — "
                "Fleets program will not be runnable until one is provisioned",
                program.title,
            )
