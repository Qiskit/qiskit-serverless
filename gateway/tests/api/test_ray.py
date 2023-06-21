"""Tests for ray util functions."""

from unittest import mock
from unittest.mock import MagicMock, patch
import requests_mock

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient

from api.models import ComputeResource
from api.ray import (
    create_ray_cluster,
    kill_ray_cluster,
)


class response:
    status = "Success"
    metadata = client.V1ObjectMeta(name="test_user")


class mock_create(MagicMock):
    def create(self, namespace, body):
        return response()


class mock_delete(MagicMock):
    def delete(self, namespace, name):
        return response()


class TestRayUtils(APITestCase):
    """Tests for ray utils."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_cluster(self):
        """Tests for cluster creation."""
        namespace = settings.RAY_KUBERAY_NAMESPACE
        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_create()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        head_node_url = "http://test_user-head-svc:8265/"
        with requests_mock.Mocker() as mocker:
            mocker.get(head_node_url, status_code=200)
            user = get_user_model().objects.first()
            compute_resource = create_ray_cluster(
                user, "test_user", "dummy yaml file contents"
            )
            self.assertIsInstance(compute_resource, ComputeResource)
            self.assertEqual(user.username, compute_resource.title)
            self.assertEqual(compute_resource.host, head_node_url)
            DynamicClient.resources.get.assert_called_once_with(
                api_version="v1alpha1", kind="RayCluster"
            )

    def test_kill_cluster(self):
        """Tests cluster deletion."""
        namespace = settings.RAY_KUBERAY_NAMESPACE

        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_delete()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        client.CoreV1Api = MagicMock()

        success = kill_ray_cluster("some_cluster")
        self.assertTrue(success)
        DynamicClient.resources.get.assert_any_call(
            api_version="v1alpha1", kind="RayCluster"
        )
        DynamicClient.resources.get.assert_any_call(
            api_version="v1", kind="Certificate"
        )
        client.CoreV1Api.assert_called()
