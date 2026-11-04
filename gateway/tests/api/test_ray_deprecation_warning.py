"""Tests for the deprecation warning a run request gets when the function runs on the Ray runner."""

import logging
from unittest.mock import MagicMock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from api.domain.authentication.channel import Channel
from api.v1.views.programs.run import (
    BLOCKED_RESOURCE_WARNING,
    RAY_DEPRECATION_WARNING_CUSTOM,
    RAY_DEPRECATION_WARNING_PROVIDER,
)
from core.config_key import ConfigKey
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import BlockedCloudResource, Config, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


def _run(program_kwargs=None, provider=None, **identity):
    """Authorize a user, create a function (custom, or provider when ``provider`` is given), run it.

    For a provider function the user is granted the run_program permission through a group that is
    also one of the function's instances, which is how legacy authorization grants run access.
    """
    token = MagicMock()
    token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
    token.channel = Channel.LOCAL
    token.token = b"test-token"
    token.instance = "instance"
    token.account_id = identity.get("account_id", "acct")
    token.plan_id = identity.get("plan_id", "plan")
    token.subscription_id = identity.get("subscription_id", "sub")
    client = APIClient()
    user = TestUtils.authorize_client(user="test_user", client=client, token=token)

    kwargs = dict(program_kwargs or {})
    run_data = {"title": "my-func", "arguments": "{}", "config": {}}
    if provider:
        TestUtils.get_or_create_group(group="runner", permissions=[["run_program", "api", "program"]])
        TestUtils.add_user_to_group(user, "runner")
        kwargs.update(provider=provider, author="other-author", instances=["runner"])
        run_data["provider"] = provider
    else:
        kwargs.setdefault("author", user)

    TestUtils.create_program(program_title="my-func", **kwargs)
    return client.post("/api/v1/programs/run/", data=run_data, format="json")


def test_a_ray_custom_function_warns_to_migrate():
    response = _run(program_kwargs={"runner": Program.RAY})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["warning"] == RAY_DEPRECATION_WARNING_CUSTOM
    assert 'runner="fleets"' in response.data["warning"]


def test_a_ray_provider_function_warns_to_contact_the_vendor():
    response = _run(program_kwargs={"runner": Program.RAY}, provider="my-provider")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["warning"] == RAY_DEPRECATION_WARNING_PROVIDER
    assert "vendor" in response.data["warning"]
    # The sentence is one clean clause, not a broken concatenation ("migrate it.to the Fleets runner.").
    assert "migrate it to the Fleets runner." in response.data["warning"]


def test_a_fleets_function_gets_no_deprecation_warning(default_ce_project):
    response = _run()

    assert response.status_code == status.HTTP_200_OK
    # No warning field at all: a plain Fleets run is neither deprecated nor blocked.
    assert "warning" not in response.data


def test_a_ray_function_that_is_also_blocked_gets_both_warnings():
    """Both conditions write the warning field; neither must drop the other, deprecation first."""
    Config.add_defaults()
    Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "true")
    # Global matching: the block has no region and blocks() now takes the instance CRN's region.
    Config.set(ConfigKey.BLOCKED_RESOURCES_REGIONAL, "false")
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="sub")

    response = _run(program_kwargs={"runner": Program.RAY})

    assert response.status_code == status.HTTP_200_OK
    warning = response.data["warning"]
    assert warning == f"{RAY_DEPRECATION_WARNING_CUSTOM} {BLOCKED_RESOURCE_WARNING}"


def test_a_ray_run_is_logged_server_side(caplog):
    with caplog.at_level(logging.WARNING, logger="api.api.v1.views.programs.run"):
        _run(program_kwargs={"runner": Program.RAY})

    assert any("deprecated platform" in record.message for record in caplog.records)


def test_a_fleets_run_is_not_logged_as_deprecated(default_ce_project, caplog):
    with caplog.at_level(logging.WARNING, logger="api.api.v1.views.programs.run"):
        _run()

    assert not any("deprecated platform" in record.message for record in caplog.records)
