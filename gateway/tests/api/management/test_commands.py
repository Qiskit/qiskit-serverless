"""Tests for commands."""
from allauth.socialaccount.models import SocialApp
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock
from django.contrib.sites.models import Site

from api.models import ComputeResource, Job
from api.ray import JobHandler


class TestCommands(APITestCase):
    """Tests for commands."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_compute_resource(self):
        """Tests compute resource creation command."""
        call_command("create_compute_resource", "test_host")
        resources = ComputeResource.objects.all()
        self.assertTrue(
            "Ray cluster default" in [resource.title for resource in resources]
        )

    def test_create_social_application(self):
        """Tests create social application command."""
        call_command(
            "create_social_application",
            host="social_app_host",
            client_id="social_app_client_id",
        )
        social_app = SocialApp.objects.get(provider="keycloak")
        site = Site.objects.get(name="social_app_host")
        self.assertEqual(social_app.client_id, "social_app_client_id")
        self.assertEqual(site.name, "social_app_host")
