"""Tests the bound on the size of a request body.

DATA_UPLOAD_MAX_MEMORY_SIZE is Django's own setting and defaults to 2.5 MB. It used not to apply to a
JSON body at all, because Django REST Framework read the request stream directly, until its 3.17.2
routed JSON and form bodies through HttpRequest.body, where Django enforces that default. An ordinary
batch of circuits then became a RequestDataTooBig, reported as a 500 by the endpoint decorator's
blanket handler. The gateway now sets the limit explicitly and reports going over it as a 413.
"""

import json

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tests.utils import TestUtils


@pytest.mark.django_db
class TestRequestBodySize:
    """POST /programs/run with a body around the limit."""

    @pytest.fixture
    def client(self):
        return APIClient()

    @staticmethod
    def _run(client, arguments, **program_kwargs):
        user = TestUtils.authorize_client(user="test-user", client=client)
        TestUtils.create_program(program_title="my-func", author=user, **program_kwargs)
        return client.post(
            "/api/v1/programs/run/",
            data={"title": "my-func", "arguments": arguments, "config": {"workers": 1}},
            format="json",
        )

    def test_run_accepts_a_batch_of_circuits(self, client):
        """A body over Django's 2.5 MB default is accepted, which is what a batch of circuits needs."""
        # One 100 qubit, depth 100 circuit is about 39 KB of base64, so this stands for a batch of
        # about seventy five of them, and is over the 2.5 MB Django would have allowed on its own.
        arguments = json.dumps({"circuits": "x" * 3 * 1024 * 1024})

        response = self._run(client, arguments)

        assert response.status_code == status.HTTP_200_OK

    def test_run_accepts_a_batch_of_circuits_against_a_schema(self, client):
        """The same batch is accepted when the function declares a schema, so it is under both limits."""
        arguments = json.dumps({"circuits": "x" * 3 * 1024 * 1024})

        response = self._run(client, arguments, arguments_schema=json.dumps({"type": "object"}))

        assert response.status_code == status.HTTP_200_OK

    def test_run_reports_an_oversized_body_as_413(self, client, settings):
        """Over the limit the caller gets a 413 naming it, not a 500 saying "Internal server error".

        Only DATA_UPLOAD_MAX_MEMORY_SIZE is set here, not MAX_REQUEST_BODY_SIZE_MB which normally
        derives it, so the message is asserted to report whatever actually did the refusing.
        """
        settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
        arguments = json.dumps({"circuits": "x" * 3 * 1024 * 1024})

        response = self._run(client, arguments)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["message"] == "the request body is larger than the maximum of 1 MB"

    def test_the_body_limit_derives_from_the_setting(self, settings):
        """MAX_REQUEST_BODY_SIZE_MB is what a deployment sets; Django reads the byte count it derives."""
        assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == settings.MAX_REQUEST_BODY_SIZE_MB * 1024 * 1024
