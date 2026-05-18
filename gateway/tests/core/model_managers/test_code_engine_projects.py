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

"""Tests for CodeEngineProjectQuerySet."""

import pytest
from django.test import override_settings

from core.models import CodeEngineProject

pytestmark = pytest.mark.django_db


def _make_project(**kwargs):
    defaults = {
        "project_id": "proj-id",
        "project_name": "test-project",
        "region": "us-east",
        "resource_group_id": "rg-id",
        "subnet_pool_id": "subnet-id",
        "pds_name_state": "pds-state",
        "pds_name_users": "pds-users",
        "pds_name_providers": "pds-providers",
        "active": True,
    }
    defaults.update(kwargs)
    return CodeEngineProject.objects.create(**defaults)


@pytest.mark.parametrize(
    "zone_map,profile,project_zone",
    [
        ({"gx2-8x64x1l40s": "us-east-1"}, "gx2-8x64x1l40s", "us-east-1"),  # zone match
        ({}, "cx3d-4x16", None),  # profile not in map → fallback
        ({"cx3d-4x16": "any"}, "cx3d-4x16", None),  # "any" → fallback
        ({}, None, None),  # no profile → fallback
    ],
)
def test_select_for_profile_zone_routing(zone_map, profile, project_zone):
    """select_for_profile() routes to zone-specific or multi-zone project correctly."""
    project = _make_project(zone=project_zone)

    with override_settings(FLEETS_PROFILE_ZONE_MAP=zone_map):
        result = CodeEngineProject.objects.select_for_profile(profile)

    assert result == project


def test_select_for_profile_returns_none_when_no_project_for_zone():
    """select_for_profile() returns None when no active project matches the zone."""
    _make_project(zone=None)  # exists but wrong zone

    with override_settings(FLEETS_PROFILE_ZONE_MAP={"gx2-8x64x1l40s": "us-east-1"}):
        assert CodeEngineProject.objects.select_for_profile("gx2-8x64x1l40s") is None


def test_select_for_profile_returns_none_when_no_active_project():
    """select_for_profile() returns None when no active project exists."""
    with override_settings(FLEETS_PROFILE_ZONE_MAP={}):
        assert CodeEngineProject.objects.select_for_profile(None) is None
