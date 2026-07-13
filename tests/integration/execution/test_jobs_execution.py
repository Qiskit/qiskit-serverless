# pylint: disable=import-error, invalid-name
"""Tests jobs."""

from datetime import datetime, timezone
import os
import tempfile
from time import sleep
from uuid import uuid4

from pytest import raises, mark

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
    QiskitServerlessException,
)
from utils import wait_for_logs, wait_for_terminal_state

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")


class TestJobs:
    """Test class for integration testing with docker."""

    def _upload_with_template(self, serverless_client: ServerlessClient, file: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", delete=True, dir=resources_path, suffix=".py"
        ) as tmp:

            with open(
                "../gateway/templates/main.tmpl",
                "r",
                encoding="utf-8",
            ) as template:
                template_content = template.read()
                template_content = template_content.replace("{{mount_path}}", "/runner")
                template_content = template_content.replace("{{package_name}}", file)
                tmp.write(template_content)
                tmp.flush()

            uploaded_function = QiskitFunction(
                title="exception_producer",
                entrypoint=os.path.basename(tmp.name),
                working_dir=resources_path,
            )

            return serverless_client.upload(uploaded_function)

    @mark.order(1)
    def test_simple_function(self, serverless_client: ServerlessClient):
        """Integration test function uploading."""
        simple_function = QiskitFunction(
            title="gold-path",
            entrypoint="gold-path-function.py",
            working_dir=resources_path,
        )

        runnable_function = serverless_client.upload(simple_function)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        runnable_function = serverless_client.function(simple_function.title)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        job = runnable_function.run()

        wait_for_logs(job, "DELAY STARTS")

        print(f"Execution logs until DELAY STARTS {job.job_id}")
        print(job.logs())
        print("-----")

        wait_for_terminal_state(job)

        expected_result = """INFO: User log
INFO: User multiline
INFO: log
WARNING: User log
ERROR: User log
DELAY STARTS
INFO: Provider log
INFO: Provider multiline
INFO: log
WARNING: Provider log
ERROR: Provider log
"""

        assert job.logs().endswith(expected_result)

        with raises(QiskitServerlessException) as exc_info:
            job.provider_logs()

        expected_error = f"""
| Message: Http bad request.
| Code: 403
| Details: You don't have access to job [{job.job_id}]
""".strip()
        assert str(exc_info.value).strip() == expected_error

        # pylint: disable=duplicate-code
        assert job is not None
        assert job.result() is not None
        allowed_keys = {"00", "11"}
        for entry in job.result().get("results", []):
            assert set(entry.keys()).issubset(allowed_keys)

        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    #     def test_function_with_arguments(self, serverless_client: ServerlessClient):
    #         """Integration test for Functions with arguments."""
    #         circuit = QuantumCircuit(2)
    #         circuit.h(0)
    #         circuit.cx(0, 1)
    #         circuit.measure_all()
    #         circuit.draw()

    #         arguments_function = QiskitFunction(
    #             title="pattern-with-arguments",
    #             entrypoint="pattern_with_arguments.py",
    #             working_dir=resources_path,
    #         )

    #         runnable_function = serverless_client.upload(arguments_function)

    #         job = runnable_function.run(circuit=circuit)

    #         assert job is not None
    #         assert job.result() is not None
    #         allowed_keys = {"00", "11"}
    #         for entry in job.result().get("results", []):
    #             assert set(entry.keys()).issubset(allowed_keys)
    #         assert job.status() == "DONE"
    #         assert isinstance(job.logs(), str)

    #     def test_logs(self, serverless_client: ServerlessClient):
    #         """Integration test for logs."""

    #         function = QiskitFunction(
    #             title="logs_function", entrypoint="logger.py", working_dir=resources_path, env_vars={"DELAY": "10"}
    #         )
    #         function = serverless_client.upload(function)
    #         job = function.run()

    #         wait_for_logs(job, "DELAY STARTS")

    #         print(f"Execution logs until DELAY STARTS {job.job_id}")
    #         print(job.logs())
    #         print("-----")

    #         wait_for_terminal_state(job)

    #         expected_result = """INFO: User log
    # INFO: User multiline
    # INFO: log
    # WARNING: User log
    # ERROR: User log
    # DELAY STARTS
    # INFO: Provider log
    # INFO: Provider multiline
    # INFO: log
    # WARNING: Provider log
    # ERROR: Provider log
    # """

    #         assert job.logs().endswith(expected_result)

    #         with raises(QiskitServerlessException) as exc_info:
    #             job.provider_logs()

    #         expected_error = f"""
    # | Message: Http bad request.
    # | Code: 403
    # | Details: You don't have access to job [{job.job_id}]
    # """.strip()

    #         assert str(exc_info.value).strip() == expected_error

    # failed jobs has logs "", so the result() can't get the error from the logs
    def test_function_with_import_errors(self, serverless_client: ServerlessClient):
        """Integration test for faulty function run."""
        function = QiskitFunction(
            title="pattern-with-errors",
            entrypoint="pattern_with_errors.py",
            working_dir=resources_path,
        )

        runnable_function = serverless_client.upload(function)

        assert runnable_function is not None

        job = runnable_function.run()

        assert job is not None
        expected_message = "ImportError: attempted relative import with no known parent package"

        with raises(QiskitServerlessException) as exc_info:
            job.result()

        assert expected_message in str(exc_info.value)

        assert job.status() == "ERROR"
        assert isinstance(job.logs(), str)

    @mark.skip(reason="Works in docker compose but tails in k8s/staging/production")
    def test_update_sub_status(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        function = QiskitFunction(
            title="pattern-with-sub-status",
            entrypoint="pattern_with_sub_status_and_wait.py",
            working_dir=resources_path,
        )
        runnable_function = serverless_client.upload(function)

        job = runnable_function.run()

        while job.status() == "QUEUED" or job.status() == "INITIALIZING":
            sleep(1)

        assert job.status() == "RUNNING: MAPPING"

    @mark.skip(reason="Works in docker compose but tails in k8s/staging/production")
    def test_execute_functions_in_parallel(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        function_1 = QiskitFunction(
            title="parallel-exec-1",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        function_2 = QiskitFunction(
            title="parallel-exec-2",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        runnable_function_1 = serverless_client.upload(function_1)
        runnable_function_2 = serverless_client.upload(function_2)

        job_1 = runnable_function_1.run()
        job_2 = runnable_function_2.run()

        while job_1.status() == "QUEUED" or job_1.status() == "INITIALIZING":
            sleep(1)

        while job_2.status() == "QUEUED" or job_2.status() == "INITIALIZING":
            sleep(1)

        assert job_1.status() == "RUNNING"
        assert job_2.status() == "RUNNING"

    def test_wrong_function_name(self, serverless_client: ServerlessClient):
        """Integration test for retrieving a function that isn't accessible."""

        arguments_function = QiskitFunction(
            title="pattern-with-arguments",
            entrypoint="pattern_with_arguments.py",
            working_dir=resources_path,
        )

        expected_message = (
            "\n| Message: Http bad request.\n| Code: 404\n| Details: Qiskit Function wrong-title doesn't exist."
        )

        serverless_client.upload(arguments_function)

        with raises(QiskitServerlessException) as exc_info:
            serverless_client.function("wrong-title")

        assert str(exc_info.value) == expected_message

    def test_events(self, serverless_client: ServerlessClient):
        """Integration test for submitting an error event within the function and retrieving it client-side."""

        events_function = QiskitFunction(
            title="event_error_producer",
            entrypoint="event_error_producer.py",
            working_dir=resources_path,
        )

        events_function = serverless_client.upload(events_function)

        job = events_function.run()

        job.result()

        events = job.events(type="ERROR")
        assert len(events) == 1

        event_data = events[0].data
        assert event_data["code"] == "1000"
        assert event_data["message"] == "My error message"
        assert event_data["args"]["my-arg-1"] == 123
        assert event_data["args"]["my-arg-2"] == "hi"

        with raises(QiskitServerlessException) as exc_info:
            job.events(type="NotValidJobEventType")

        assert "Type is not valid. Valid types: ['ERROR']" in str(exc_info.value)

    def test_serverless_error_raise(self, serverless_client: ServerlessClient):
        """Integration test for submitting an error event within the function and retrieving it client-side."""

        events_function = self._upload_with_template(serverless_client, "exception_producer_serverless_error")

        job = events_function.run()

        with raises(QiskitServerlessException) as exc_info:
            job.result()

        events = job.events(type="ERROR")
        assert len(events) == 1

        expected_message = """
| Message: My error message
| Code: A123
| Exception: PartnerError
| Details:
|   - my-args: 123
""".strip()

        assert exc_info.value.args[0].strip() == expected_message

        event_data = events[0].data
        assert event_data["code"] == "A123"
        assert event_data["message"] == "My error message"
        assert event_data["args"]["my-args"] == 123
        assert expected_message == job.error_message().strip()

    def test_other_error_raise(self, serverless_client: ServerlessClient):
        """Integration test for submitting an error event within the function and retrieving it client-side."""

        events_function = self._upload_with_template(serverless_client, "exception_producer_other_error")

        job = events_function.run()

        with raises(QiskitServerlessException) as exc_info:
            job.result()

        events = job.events(type="ERROR")
        assert len(events) == 1

        expected_message = "\n| Message: ValueError: This is not a ServerlessError\n| Code: 1\n| Exception: ValueError"
        assert exc_info.value.args[0] == expected_message

        event_data = events[0].data
        assert event_data["code"] == "1"
        assert event_data["message"] == "ValueError: This is not a ServerlessError"
        assert event_data["exception"] == "ValueError"
        assert expected_message == job.error_message()
