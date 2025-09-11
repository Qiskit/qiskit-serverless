"""Tests job."""

# pylint: disable=too-few-public-methods
import json
import os
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest
import requests_mock

from qiskit.circuit.random import random_circuit

from qiskit_serverless import ServerlessClient
from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_ACCESS_TRIAL,
)
from qiskit_serverless.core.jobs import (
    Job,
    is_running_in_serverless,
    save_result,
    is_trial,
    update_status,
    Workflow,
)

from qiskit_serverless.core.functions import (
    QiskitFunctionStep,
    QiskitFunction,
    RunnableQiskitFunctionWithSteps,
)


class PostFunctionResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = json.dumps(
        {
            "id": 1000,
            "title": "My stepped function",
            "description": "My description",
            "steps": [
                {
                    "id": 2000,
                    "base_function": 1000,
                    "function": 1001,
                },
                {
                    "id": 2001,
                    "base_function": 1000,
                    "function": 1002,
                    "depends_on": 2000,
                },
            ],
        }
    )


class GetFunctionResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = json.dumps(
        {
            "title": "My title",
            "provider": "My provider",
            "description": "My description",
            "entrypoint": "main.py",
            "steps": [],
        }
    )


class GetSteppedFunctionResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = json.dumps(
        {
            "id": 1000,
            "title": "My stepped function",
            "description": "My description",
            "steps": [
                {
                    "id": 2000,
                    "base_function": 1000,
                    "function": 1001,
                },
                {
                    "id": 2001,
                    "base_function": 1000,
                    "function": 1002,
                    "depends_on": 2000,
                },
            ],
        }
    )


class PostWorkflowResponseMock:
    """Utility class to mock request.get response with a json"""

    ok = True
    text = json.dumps(
        {
            "id": 3000,
            "user": "Me",
            "function": 1000,
            "jobs": [
                {
                    "id": 4000,
                    "workflow_id": 3000,
                    "workflow_function": 1000,
                },
                {
                    "id": 4001,
                    "workflow_id": 3000,
                    "workflow_function": 1000,
                    "depends_on": 4000,
                },
            ],
        }
    )


class TestWorkflow:
    @patch("requests.post", Mock(return_value=PostFunctionResponseMock()))
    @patch("requests.get", Mock(return_value=GetFunctionResponseMock()))
    def test_upload_stepped_function(self):
        """Tests update sub status."""

        client = ServerlessClient(host="host", token="token", version="version")

        f1 = client.function("My title")
        f2 = client.function("My title")

        f = QiskitFunction("My stepped function", steps=[f1, f2])

        runnable_function = client.upload(f)

        assert isinstance(runnable_function, RunnableQiskitFunctionWithSteps)
        assert len(runnable_function.steps) == 2

    @patch("requests.post", Mock(return_value=PostWorkflowResponseMock()))
    @patch("requests.get", Mock(return_value=GetSteppedFunctionResponseMock()))
    def test_upload_run_stepped_function(self):
        """Tests update sub status."""

        client = ServerlessClient(host="host", token="token", version="version")

        runnable_function = client.function("My stepped function")

        workflow = runnable_function.run()

        assert isinstance(workflow, Workflow)
        assert len(workflow.jobs) == 2
