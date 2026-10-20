"""Tests for a run request while Code Engine is temporarily unavailable."""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.domain.exceptions.retryable_error import RetryableError
from core.models import ComputeProfile, FunctionSize, Job, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


def test_run_returns_503_when_code_engine_is_unavailable():
    api_client = APIClient()
    user = TestUtils.authorize_client(user="test_user", client=api_client)
    ce_project = TestUtils.get_or_create_ce_project(
        project_name="test-project",
        project_id="test-ce-project-id",
        cos_bucket_user_data_name="user-bucket",
        cos_bucket_provider_data_name="provider-bucket",
        cos_instance_name="cos-instance",
        cos_key_name="cos-key",
    )
    program = TestUtils.create_program(
        program_title="test-program", author=user, runner=Program.FLEETS, code_engine_project=ce_project
    )
    profile, _ = ComputeProfile.objects.get_or_create(compute_profile_id="16x128")
    FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)

    with patch(
        "core.services.storage.arguments_storage_fleets.FleetsArgumentsStorage.save",
        side_effect=RetryableError("Code Engine API error: Too Many Requests"),
    ):
        response = api_client.post(
            reverse("v1:programs-run"),
            {"title": program.title, "arguments": "{}", "config": {}, "function_size": "m"},
            format="json",
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "please retry" in response.data["message"]
    assert not Job.objects.exists()
