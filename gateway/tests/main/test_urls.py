"""Tests for the top-level URL routing."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_root_redirects_to_swagger():
    response = Client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/swagger/"


@pytest.mark.django_db
def test_swagger_schema_generates_without_error():
    response = Client().get("/swagger/?format=openapi")

    assert response.status_code == 200
