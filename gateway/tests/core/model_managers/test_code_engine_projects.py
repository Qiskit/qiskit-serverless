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

"""Unit tests for core.model_managers.code_engine_projects."""

import pytest
from unittest.mock import MagicMock, patch

from core.model_managers.code_engine_projects import select_ce_project

_MOD = "core.model_managers.code_engine_projects"


@pytest.mark.parametrize(
    "zone_map,profile,expect_zone_filter",
    [
        ({"gx2-8x64x1l40s": "us-east-1"}, "gx2-8x64x1l40s", "us-east-1"),  # zone match
        ({}, "cx3d-4x16", None),  # profile not in map → fallback
        ({"cx3d-4x16": "any"}, "cx3d-4x16", None),  # "any" → fallback
        ({}, None, None),  # no profile → fallback
    ],
)
def test_select_ce_project_zone_routing(zone_map, profile, expect_zone_filter):
    """select_ce_project() routes to zone-specific or multi-zone project correctly."""
    mock_project = MagicMock()
    mock_qs = MagicMock()
    mock_qs.filter.return_value.first.return_value = mock_project

    with patch(f"{_MOD}.settings") as mock_settings, patch(f"{_MOD}.CodeEngineProject") as mock_ce:
        mock_settings.FLEETS_PROFILE_ZONE_MAP = zone_map
        mock_ce.objects.filter.return_value = mock_qs

        result = select_ce_project(profile)

    assert result is mock_project
    if expect_zone_filter:
        mock_qs.filter.assert_called_once_with(zone=expect_zone_filter)
    else:
        mock_qs.filter.assert_any_call(zone__isnull=True)


@pytest.mark.parametrize(
    "zone_map,profile,none_qs,match",
    [
        ({"gx2-8x64x1l40s": "us-east-1"}, "gx2-8x64x1l40s", False, "us-east-1"),
        ({}, None, True, "No active Code Engine project available"),
    ],
)
def test_select_ce_project_raises(zone_map, profile, none_qs, match):
    """select_ce_project() raises ValueError when no suitable project is found."""
    mock_qs = MagicMock()
    mock_qs.filter.return_value.first.return_value = None
    if none_qs:
        mock_qs.first.return_value = None

    with patch(f"{_MOD}.settings") as mock_settings, patch(f"{_MOD}.CodeEngineProject") as mock_ce:
        mock_settings.FLEETS_PROFILE_ZONE_MAP = zone_map
        mock_ce.objects.filter.return_value = mock_qs

        with pytest.raises(ValueError, match=match):
            select_ce_project(profile)
