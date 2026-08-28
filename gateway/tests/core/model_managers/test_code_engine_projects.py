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
    """Tests for CodeEngineProject.objects.select_default()."""

    def test_returns_none_when_configured_name_not_found(self, settings):
        """Returns None when CE_DEFAULT_PROJECT_NAME doesn't match any active project."""
        settings.CE_DEFAULT_PROJECT_NAME = "nonexistent"
        TestUtils.get_or_create_ce_project(project_name="other", project_id="p1")

        assert CodeEngineProject.objects.select_default() is None

    def test_skips_inactive_project(self, settings):
        """Inactive project with matching name is not selected."""
        settings.CE_DEFAULT_PROJECT_NAME = "my-project"
        TestUtils.get_or_create_ce_project(project_name="my-project", project_id="p1", active=False)

        assert CodeEngineProject.objects.select_default() is None

    def test_skips_project_dedicated_to_a_provider(self, settings):
        """A project matching the default name but dedicated to a provider is not the default."""
        settings.CE_DEFAULT_PROJECT_NAME = "my-project"
        project = TestUtils.get_or_create_ce_project(project_name="my-project", project_id="p1")
        TestUtils.get_or_create_provider("acme", code_engine_project=project)

        assert CodeEngineProject.objects.select_default() is None


@pytest.mark.django_db
class TestAssignToProgram:
    """Tests for CodeEngineProject.objects.assign_to_program()."""

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

        CodeEngineProject.objects.assign_to_program(program)

        assert program.code_engine_project == other

    def test_does_not_persist_to_db(self, ce_project):
        """Caller is responsible for saving — assignment is in-memory only."""
        program = TestUtils.create_program(program_title="unsaved", author="user1", runner=Program.FLEETS)

        CodeEngineProject.objects.assign_to_program(program)
        program.refresh_from_db()

        assert program.code_engine_project is None

    def test_provider_program_gets_dedicated_project(self, ce_project):
        """A provider with a dedicated project is assigned that project, not the default."""
        dedicated = TestUtils.get_or_create_ce_project(project_name="acme-project", project_id="proj-acme")
        TestUtils.get_or_create_provider("acme", code_engine_project=dedicated)
        program = TestUtils.create_program(
            program_title="acme-func", author="user1", provider="acme", runner=Program.FLEETS
        )

        CodeEngineProject.objects.assign_to_program(program)

        assert program.code_engine_project == dedicated

    def test_each_provider_gets_its_own_project(self, ce_project):
        """With several dedicated projects, each program gets the one for its own provider.

        Both directions are asserted in one test on purpose: an implementation that
        ignored which provider a project belongs to would return the same project for
        both programs and so fail one of the assertions, whichever it picked.
        """
        acme = TestUtils.get_or_create_ce_project(project_name="acme-project", project_id="proj-acme")
        other = TestUtils.get_or_create_ce_project(project_name="other-project", project_id="proj-other")
        TestUtils.get_or_create_provider("acme", code_engine_project=acme)
        TestUtils.get_or_create_provider("other", code_engine_project=other)
        acme_program = TestUtils.create_program(
            program_title="acme-func", author="user1", provider="acme", runner=Program.FLEETS
        )
        other_program = TestUtils.create_program(
            program_title="other-func", author="user1", provider="other", runner=Program.FLEETS
        )

        CodeEngineProject.objects.assign_to_program(acme_program)
        CodeEngineProject.objects.assign_to_program(other_program)

        assert acme_program.code_engine_project == acme
        assert other_program.code_engine_project == other

    def test_two_providers_share_one_project(self, ce_project):
        """Two providers dedicated to the same project (e.g. ibm/ibm-dev) both get it."""
        shared = TestUtils.get_or_create_ce_project(project_name="shared-project", project_id="proj-shared")
        TestUtils.get_or_create_provider("ibm", code_engine_project=shared)
        TestUtils.get_or_create_provider("ibm-dev", code_engine_project=shared)
        ibm_program = TestUtils.create_program(
            program_title="ibm-func", author="user1", provider="ibm", runner=Program.FLEETS
        )
        ibm_dev_program = TestUtils.create_program(
            program_title="ibm-dev-func", author="user1", provider="ibm-dev", runner=Program.FLEETS
        )

        CodeEngineProject.objects.assign_to_program(ibm_program)
        CodeEngineProject.objects.assign_to_program(ibm_dev_program)

        assert ibm_program.code_engine_project == shared
        assert ibm_dev_program.code_engine_project == shared

    def test_provider_without_dedicated_project_is_left_unassigned(self, ce_project):
        """A provider with no dedicated project is not given the default project."""
        program = TestUtils.create_program(
            program_title="other-func", author="user1", provider="other", runner=Program.FLEETS
        )

        CodeEngineProject.objects.assign_to_program(program)

        assert program.code_engine_project is None

    def test_inactive_dedicated_project_is_left_unassigned(self, ce_project):
        """An inactive dedicated project is ignored and the default is not substituted."""
        inactive = TestUtils.get_or_create_ce_project(project_name="acme-project", project_id="proj-acme", active=False)
        TestUtils.get_or_create_provider("acme", code_engine_project=inactive)
        program = TestUtils.create_program(
            program_title="acme-inactive", author="user1", provider="acme", runner=Program.FLEETS
        )

        CodeEngineProject.objects.assign_to_program(program)

        assert program.code_engine_project is None

    def test_custom_program_gets_default_project(self, ce_project):
        """A function without a provider is assigned the default project."""
        dedicated = TestUtils.get_or_create_ce_project(project_name="acme-project", project_id="proj-acme")
        TestUtils.get_or_create_provider("acme", code_engine_project=dedicated)
        program = TestUtils.create_program(program_title="custom-func", author="user1", runner=Program.FLEETS)

        CodeEngineProject.objects.assign_to_program(program)

        assert program.code_engine_project == ce_project
