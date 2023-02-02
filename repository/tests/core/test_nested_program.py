from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from api.models import NestedProgram


class NestedProgramTests(APITestCase):

    fixtures = ["tests/fixtures/initial_data.json"]

    def test_get_nested_program(self):
        """
        Retrieve information about a specific nested program
        """
        url = reverse("nested-programs-detail", args=[1])
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
