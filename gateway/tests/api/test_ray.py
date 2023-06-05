"""Tests for ray util functions."""

from unittest import mock
import requests_mock

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from api.models import ComputeResource
from api.ray import (
    create_compute_template_if_not_exists,
    create_ray_cluster,
    kill_ray_cluster,
)


class TestRayUtils(APITestCase):
    """Tests for ray utils."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_compute_template(self):
        """Tests for create compute template."""
        kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
        namespace = settings.RAY_KUBERAY_NAMESPACE
        template_name = settings.RAY_KUBERAY_DEFAULT_TEMPLATE_NAME

        template_url = (
            f"{kube_ray_api_server_host}/apis/v1alpha2/"
            f"namespaces/{namespace}/compute_templates"
        )

        with requests_mock.Mocker() as mocker:
            mocker.get(f"{template_url}/{template_name}", status_code=404)
            mocker.post(template_url)

            create_compute_template_if_not_exists()

    def test_create_cluster(self):
        """Tests for cluster creation."""
        kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
        namespace = settings.RAY_KUBERAY_NAMESPACE
        template_name = settings.RAY_KUBERAY_DEFAULT_TEMPLATE_NAME

        clusters_url = (
            f"{kube_ray_api_server_host}/apis/v1alpha2/namespaces/{namespace}/clusters"
        )
        template_url = (
            f"{kube_ray_api_server_host}/apis/v1alpha2/"
            f"namespaces/{namespace}/compute_templates"
        )
        head_node_url = "http://test_user-head-svc:8265/"
        with requests_mock.Mocker() as mocker:
            mocker.get(f"{template_url}/{template_name}", status_code=404)
            mocker.post(template_url)
            mocker.post(clusters_url, status_code=200)
            mocker.get(head_node_url, status_code=200)

            user = get_user_model().objects.first()
            compute_resource = create_ray_cluster(user, "test_user")
            self.assertIsInstance(compute_resource, ComputeResource)
            self.assertEqual(user.username, compute_resource.title)
            self.assertEqual(compute_resource.host, head_node_url)

    def test_kill_cluster(self):
        """Tests cluster deletion."""
        kube_ray_api_server_host = settings.RAY_KUBERAY_API_SERVER_URL
        namespace = settings.RAY_KUBERAY_NAMESPACE
        url = f"{kube_ray_api_server_host}/apis/v1alpha2/namespaces/{namespace}/clusters/some_cluster"

        with requests_mock.Mocker() as mocker:
            mocker.delete(url, status_code=200)

            success = kill_ray_cluster("some_cluster")
            self.assertTrue(success)
