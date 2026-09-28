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

"""
Resolve a Code Engine project name to the project it names.

These are module-level functions rather than methods on
:class:`~core.ibm_cloud.code_engine.fleets.handler.FleetHandler`, because the handler takes
a ``project_id`` in its constructor: it is already scoped to one project and so cannot be
the thing that finds one.
"""

import logging
from typing import Any

from core.ibm_cloud.code_engine.ce_client import ApiClient
from core.ibm_cloud.code_engine.ce_client.api.projects_api import ProjectsApi
from core.ibm_cloud.code_engine.ce_client.models.v2_project import V2Project

logger = logging.getLogger("ce_projects")

# Code Engine reports a project's lifecycle state here; only an active one can run work.
# Real states seen in the account include "active" and "preparing".
ACTIVE_STATUS = "active"


def list_projects(ce_api_client: ApiClient) -> list[V2Project]:
    """Return every project in the account, following pagination.

    Separate from :func:`pick_project` so a caller seeding many projects can list once and
    match each entry against the result, rather than paying an IAM token fetch and a list
    call per entry. The listing is account-wide, not scoped to the region of the host it is
    called on, which is why :func:`pick_project` has to filter on region.

    Args:
        ce_api_client: Authenticated CE :class:`ApiClient`.

    Returns:
        A list of ``V2Project`` objects.

    Raises:
        ApiException: When a CE list call fails.
        RuntimeError: When a page repeats the token of the page before it, which would
            otherwise loop forever.
    """
    projects_api = ProjectsApi(ce_api_client)
    projects: list[V2Project] = []
    seen_tokens: set[str] = set()
    start: str | None = None
    while True:
        kwargs: dict[str, Any] = {"start": start} if start else {}
        page = projects_api.list_projects(**kwargs)
        projects.extend(page.projects or [])
        nxt = getattr(page, "next", None)
        start = getattr(nxt, "start", None) if nxt else None
        if not start:
            return projects
        if start in seen_tokens:
            raise RuntimeError(f"Code Engine repeated the project page token [{start}]; refusing to page forever")
        seen_tokens.add(start)


def pick_project(projects: list[V2Project], *, name: str, region: str) -> V2Project:
    """Return the single active project with this name in this region.

    Filtering on ``region`` is required rather than defensive: ``GET /v2/projects`` lists
    every project in the account whichever regional host it is called on, so two projects
    sharing a name in different regions would otherwise both match.

    Filtering on status is required too. A project that is still ``preparing`` has an id
    and a resource group but cannot run anything, so seeding it would produce a row that
    looks complete and fails at submit time.

    Args:
        projects: Projects to match against, from :func:`list_projects`.
        name: The project name to resolve.
        region: IBM Cloud region the project must be in.

    Returns:
        The matching ``V2Project``; the caller reads ``id`` and ``resource_group_id``.

    Raises:
        ValueError: When no project, no *active* project, or more than one active project
            carries the name in that region.
    """
    in_region = [p for p in projects if p.region == region]
    named = [p for p in in_region if p.name == name]

    if not named:
        available = sorted(p.name for p in in_region if p.status == ACTIVE_STATUS)
        raise ValueError(
            f"No Code Engine project named '{name}' in region [{region}]. Active projects there: {available}"
        )

    active = [p for p in named if p.status == ACTIVE_STATUS]
    if not active:
        states = ", ".join(f"id={p.id} status={p.status}" for p in named)
        raise ValueError(
            f"Code Engine project '{name}' in region [{region}] is not active ({states}). A project that is "
            f"still being prepared cannot run work, so it is not seeded."
        )

    if len(active) > 1:
        details = ", ".join(f"id={p.id}" for p in active)
        raise ValueError(
            f"Code Engine project name '{name}' is ambiguous in region [{region}]: matches "
            f"{len(active)} active projects ({details}). Rename one of them, or configure both "
            f"project_id and resource_group_id for this entry so the name never has to be resolved."
        )

    return active[0]
