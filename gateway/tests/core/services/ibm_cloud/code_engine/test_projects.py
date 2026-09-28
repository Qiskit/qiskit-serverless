# This code is a Qiskit project.
#
# (C) Copyright IBM 2026.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for resolving a Code Engine project name to its id and resource group."""

from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.projects import ACTIVE_STATUS, list_projects, pick_project

_PROJECTS_MOD = "core.ibm_cloud.code_engine.projects"


def _project(name, project_id, region="us-east", status=ACTIVE_STATUS, resource_group_id="rg-1"):
    """Return a stub V2Project with the fields the resolver reads."""
    project = MagicMock()
    project.name = name
    project.id = project_id
    project.region = region
    project.status = status
    project.resource_group_id = resource_group_id
    return project


def _page(projects, start=None):
    """Return a stub V2ProjectList page, with a next token when start is given."""
    page = MagicMock()
    page.projects = projects
    page.next = MagicMock(start=start) if start else None
    return page


class TestPickProject:
    """pick_project matches one active project by name within a region."""

    def test_single_match_returns_it(self):
        """The one active project with that name in that region is returned."""
        projects = [_project("alpha", "id-a"), _project("beta", "id-b", resource_group_id="rg-b")]

        picked = pick_project(projects, name="beta", region="us-east")

        assert picked.id == "id-b"
        assert picked.resource_group_id == "rg-b"

    def test_region_is_part_of_the_match(self):
        """A same-named project in another region is not picked.

        The listing is account-wide whichever regional host it came from, so region has to
        be filtered here or an entry could be seeded against a project in the wrong region.
        """
        projects = [_project("shared", "id-east", region="us-east"), _project("shared", "id-de", region="eu-de")]

        assert pick_project(projects, name="shared", region="eu-de").id == "id-de"
        assert pick_project(projects, name="shared", region="us-east").id == "id-east"

    def test_non_active_project_is_refused_naming_its_status(self):
        """A project that is not active yet has an id but cannot run work."""
        projects = [_project("still-building", "id-p", status="preparing")]

        with pytest.raises(ValueError, match="not active") as raised:
            pick_project(projects, name="still-building", region="us-east")

        assert "preparing" in str(raised.value)

    def test_no_match_lists_the_active_names_available(self):
        """The error names what does exist, so a typo is obvious from the log."""
        projects = [_project("alpha", "id-a"), _project("hidden", "id-h", status="preparing")]

        with pytest.raises(ValueError, match="No Code Engine project named 'nope'") as raised:
            pick_project(projects, name="nope", region="us-east")

        message = str(raised.value)
        assert "alpha" in message
        assert "hidden" not in message  # only active projects are offered as alternatives

    def test_duplicate_active_names_raise_naming_both_ids(self):
        """Two active projects sharing a name is refused rather than guessed at."""
        projects = [_project("dup", "id-1"), _project("dup", "id-2")]

        with pytest.raises(ValueError, match="ambiguous") as raised:
            pick_project(projects, name="dup", region="us-east")

        message = str(raised.value)
        assert "id-1" in message
        assert "id-2" in message


class TestListProjects:
    """list_projects pages through the account's projects."""

    def test_follows_pagination(self):
        """A next token is followed, and the start is passed back to the API."""
        with patch(f"{_PROJECTS_MOD}.ProjectsApi") as api_cls:
            api = api_cls.return_value
            api.list_projects.side_effect = [
                _page([_project("first", "id-1")], start="tok2"),
                _page([_project("second", "id-2")]),
            ]

            projects = list_projects(MagicMock())

        assert [p.id for p in projects] == ["id-1", "id-2"]
        assert api.list_projects.call_count == 2
        assert api.list_projects.call_args_list[1].kwargs.get("start") == "tok2"

    def test_a_repeated_page_token_raises_instead_of_looping_forever(self):
        """A server echoing its own next token must not spin inside a migrations Job."""
        with patch(f"{_PROJECTS_MOD}.ProjectsApi") as api_cls:
            api_cls.return_value.list_projects.return_value = _page([_project("a", "id-a")], start="same-token")

            with pytest.raises(RuntimeError, match="refusing to page forever"):
                list_projects(MagicMock())

    def test_empty_listing_returns_empty(self):
        """No projects is an empty list, not None, so callers can filter it."""
        with patch(f"{_PROJECTS_MOD}.ProjectsApi") as api_cls:
            api_cls.return_value.list_projects.return_value = _page([])

            assert list_projects(MagicMock()) == []
