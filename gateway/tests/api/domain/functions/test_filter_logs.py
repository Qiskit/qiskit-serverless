"""Tests for filter_logs."""

from rest_framework.test import APITestCase

from api.domain.function.filter_logs import extract_public_logs


class TestFilterLogs(APITestCase):
    """Tests for filter_logs."""

    def test_extract_public_logs(self):
        """Tests compute resource creation command."""

        log = """[PUBLIC] sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Starting application
[private] sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Mapping
[PUBLIC] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Backend = {
    "name": "ibm_123"
}
third_party.run_function:INFO:2024-11-15 11:30:32,124: running_options = {
    "options_group": {
        "important": true,
        "very_important": true,
        "more_options": {
            "gigabytes": 512,
            "also_gigabytes": 512
        }
    },
}
[puBLic] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Starting
[PRIVATE] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Private information"""

        expected_output = """[PUBLIC] sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Starting application
[PUBLIC] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Backend = {
    "name": "ibm_123"
}
[puBLic] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Starting
"""

        output_log = extract_public_logs(log)

        self.assertEquals(output_log, expected_output)
