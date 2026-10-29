"""Tests for the warning a run request gets when its account, plan and subscription are blocked."""

from unittest.mock import MagicMock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from api.domain.authentication.channel import Channel
from api.v1.views.programs.run import BLOCKED_RESOURCE_WARNING
from core.config_key import ConfigKey
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import BlockedCloudResource, Config, Job
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def blocked_resources_enforced():
    """Blocked resources are not enforced by default, and these tests are about enforcing them."""
    Config.add_defaults()
    Config.set(ConfigKey.BLOCKED_RESOURCES_ENFORCED, "true")


def _run(**identity):
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
    TestUtils.create_program(program_title="my-func", author=user)
    return client.post(
        "/api/v1/programs/run/", data={"title": "my-func", "arguments": "{}", "config": {}}, format="json"
    )


def test_a_blocked_resource_gets_a_warning_and_its_job_is_still_queued():
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="sub")

    response = _run()

    assert response.status_code == status.HTTP_200_OK
    assert response.data["warning"] == BLOCKED_RESOURCE_WARNING
    assert Job.objects.get(id=response.data["id"]).status == Job.QUEUED


@pytest.mark.parametrize("identity", [{}, {"plan_id": "other"}, {"subscription_id": "other"}])
def test_a_resource_that_is_not_blocked_gets_no_warning(identity):
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="blocked-sub")

    response = _run(**identity)

    assert response.status_code == status.HTTP_200_OK
    assert "warning" not in response.data
    assert Job.objects.filter(id=response.data["id"]).exists()


def test_a_blocked_resource_gets_no_warning_while_blocked_resources_are_not_enforced():
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="sub")
    Config.set(ConfigKey.BLOCKED_RESOURCES_ENFORCED, "false")

    response = _run()

    assert response.status_code == status.HTTP_200_OK
    assert "warning" not in response.data
