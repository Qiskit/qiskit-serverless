"""Tests for filter_logs."""

from rest_framework.test import APITestCase

from api.domain.function.filter_logs import (
    filter_logs_with_public_tags,
    remove_prefix_tags_in_logs,
)


class TestFilterLogs(APITestCase):
    """Tests for filter_logs."""

    def test_extract_public_logs(self):
        """Tests compute resource creation command."""

        log = """
        
third_party.run_function:INFO:2024-11-15 11:30:32,124: third party setting up...
system 1 up...
system 2 up...
Setup complete!
[PUBLIC] sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Starting application
[private] sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Mapping
[PUBLIC] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Backend = {
[PUBLIC]     "name": "ibm_123"
[PUBLIC] }
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
[PRIVATE] sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Private information

"""

        expected_output = """sim_entrypoint.run_function:INFO:2024-10-15 11:30:32,123: Starting application
sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Backend = {
    "name": "ibm_123"
}
sim_entrypoint.run_function:INFO:2024-11-15 11:30:32,124: Starting
"""

        output_log = filter_logs_with_public_tags(log)

        self.assertEquals(output_log, expected_output)

    def test_filter_user_job_logs(self):
        """Tests log_filter_user_job removes prefixes but keeps all lines."""

        log = """[PUBLIC] Public log line 1
[PRIVATE] Private log line
Third party log (no prefix)
[PUBLIC] Public log line 2
[public] Case insensitive public
[PRIVATE] Another private line
Regular print statement
"""

        expected_output = """Public log line 1
Private log line
Third party log (no prefix)
Public log line 2
Case insensitive public
Another private line
Regular print statement
"""

        output_log = remove_prefix_tags_in_logs(log)

        self.assertEquals(output_log, expected_output)
