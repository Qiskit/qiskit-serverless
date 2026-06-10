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

"""Tests for CodeEngineProjectQuerySet model manager."""

import pytest

from core.models import CodeEngineProject, Program
from tests.utils import TestUtils


@pytest.mark.django_db
class TestSelectDefault:
    """Tests for CodeEngineProject.projects.select_default()."""

    def test_returns_none_when_configured_name_not_found(self, settings):
        """Returns None when CE_DEFAULT_PROJECT_NAME doesn't match any active project."""
        settings.CE_DEFAULT_PROJECT_NAME = "nonexistent"
        TestUtils.get_or_create_ce_project(project_name="other", project_id="p1")

        assert CodeEngineProject.projects.select_default() is None

    def test_skips_inactive_project(self, settings):
        """Inactive project with matching name is not selected."""
        settings.CE_DEFAULT_PROJECT_NAME = "my-project"
        TestUtils.get_or_create_ce_project(project_name="my-project", project_id="p1", active=False)

        assert CodeEngineProject.projects.select_default() is None


@pytest.mark.django_db
class TestAssignToProgram:
    """Tests for CodeEngineProject.projects.assign_to_program()."""

    @pytest.fixture(autouse=True)
    def _configure_default(self, settings):
        settings.CE_DEFAULT_PROJECT_NAME = "default-project"

    @pytest.fixture
    def ce_project(self):
        return TestUtils.get_or_create_ce_project(project_name="default-project", project_id="proj-default")

    def test_does_not_overwrite_existing_project(self, ce_project):
        """Existing CE project assignment is preserved."""
        other = TestUtils.get_or_create_ce_project(project_name="other-project", project_id="proj-other")
        program = TestUtils.create_program(
            program_title="pre-assigned",
            author="user1",
            runner=Program.FLEETS,
            code_engine_project=other,
        )

        CodeEngineProject.projects.assign_to_program(program)

        assert program.code_engine_project == other

    def test_does_not_persist_to_db(self, ce_project):
        """Caller is responsible for saving — assignment is in-memory only."""
        program = TestUtils.create_program(program_title="unsaved", author="user1", runner=Program.FLEETS)

        CodeEngineProject.projects.assign_to_program(program)
        program.refresh_from_db()

        assert program.code_engine_project is None
