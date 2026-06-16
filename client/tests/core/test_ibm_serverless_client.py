# This code is a Qiskit project.
#
# (C) Copyright IBM 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Test IBMServerlessClient."""

import uuid
import tempfile
import warnings
from unittest.mock import patch, MagicMock, call

import pytest
from qiskit.providers.exceptions import QiskitBackendNotFoundError

from qiskit_serverless import IBMServerlessClient
from qiskit_serverless.core.constants import (
    USAGE_LOW_THRESHOLD_SECONDS,
    USAGE_ZERO_EPSILON_SECONDS,
)
from qiskit_serverless.core.enums import Channel
from qiskit_serverless.exception import QiskitServerlessException


_LIST_INSTANCES = "qiskit_ibm_runtime.accounts.account.CloudAccount.list_instances"
_VERIFY_CREDS = "qiskit_serverless.core.clients.serverless_client.ServerlessClient._verify_credentials"
_CONFIG_FILE = "qiskit_ibm_runtime.accounts.management._DEFAULT_ACCOUNT_CONFIG_JSON_FILE"

_INSTANCE_LIST = [
    {
        "crn": "test_instance",
        "plan": "test_plan",
        "name": "test_instance",
        "tags": "",
        "pricing_type": "pay_as_you_go",
    }
]


def _make_client(mock_file_path, mock_verify, mock_list_instances, instance="test_instance"):
    """Build an IBMServerlessClient suitable for unit tests."""
    mock_list_instances.return_value = _INSTANCE_LIST
    mock_verify.return_value = None
    with tempfile.NamedTemporaryFile() as tmp:
        mock_file_path.return_value = tmp.name
    return IBMServerlessClient(token="tok", instance=instance, channel="ibm_quantum_platform")


class TestIBMServerlessClient:
    """Unit tests for IBMServerlessClient."""

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_init(self, mock_file_path, mock_verify_credentials, mock_list_instances):
        """Test __init__ with an explicit token, instance and host"""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "my_instance",
                "plan": "test_plan",
                "name": "my_instance",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            }
        ]

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        use_host = "http://other.host"
        use_token = "my_token"
        use_instance = "my_instance"
        use_channel = Channel.IBM_QUANTUM_PLATFORM.value

        # Replace the _DEFAULT_ACCOUNT_CONFIG_JSON_FILE path with a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        client = IBMServerlessClient(token=use_token, instance=use_instance, channel=use_channel, host=use_host)

        assert client.host == use_host
        assert client.channel == use_channel
        assert client.instance == use_instance
        assert client.token == use_token

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_init_with_crn(self, mock_file_path, mock_verify_credentials, mock_list_instances):
        """
        Test __init__ with an explicit IBM instance crn in the format:
        crn:version:cname:ctype:service-name:location:scope:service-instance:resource-type:resource
        Source:
        https://cloud.ibm.com/docs/account?topic=account-crn#format-crn)
        """

        instance_dic = {
            "crn": "crn:v1:bluemix:public:quantum-computing:us-east:a/my-crn::"
            "1a0ec336-f391-4091-a6fb-5e084a4c56f4:bucket:mybucket",
            "plan": "test_plan",
            "name": "my_instance_crn",
            "tags": "test_tags",
            "pricing_type": "test_pricing_type",
        }
        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [instance_dic]

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        use_host = "http://other.host"
        use_token = "my_token"
        use_instance = "my_instance_crn"
        use_channel = Channel.IBM_QUANTUM_PLATFORM.value

        # Replace the _DEFAULT_ACCOUNT_CONFIG_JSON_FILE path with a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        client = IBMServerlessClient(token=use_token, instance=use_instance, channel=use_channel, host=use_host)

        assert client.host == use_host
        assert client.channel == use_channel
        assert client.instance == instance_dic["crn"]
        assert client.token == use_token

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_save_load_account(self, mock_file_path, mock_verify_credentials, mock_list_instances):
        """Test saving and loading accounts with the IBMServerlessClient."""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "test_name",
                "plan": "test_plan",
                "name": "test_name",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            },
            {
                "crn": "dummy_crn",
                "plan": "test_plan",
                "name": "dummy_crn",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            },
        ]

        # Mock ServerlessClient credential verification
        mock_verify_credentials.return_value = None

        # Save config in a temporary file
        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

        channels_to_test = [
            Channel.IBM_CLOUD.value,
            Channel.IBM_QUANTUM_PLATFORM.value,
        ]

        instances_to_test = [
            "test_name",
            "dummy_crn",
            "dummy_crn",
        ]
        for use_channel, use_instance in zip(channels_to_test, instances_to_test):
            use_token = "save_token"
            use_name = f"test_save_account_{uuid.uuid4().hex}"
            IBMServerlessClient.save_account(
                token=use_token,
                name=use_name,
                instance=use_instance,
                channel=use_channel,
            )
            client = IBMServerlessClient(name=use_name)
            assert client.account.channel == use_channel
            assert client.account.token == use_token
            assert client.account.instance == use_instance

    def test_ibm_quantum_channel(self):
        """Test error raised when initializing account with `ibm_quantum` channel."""
        use_channel = "ibm_quantum"
        use_instance = "h/g/p"
        use_token = "save_token"

        # The error message miss a ' at the end but that is the message in qiskit ibm runtime
        with pytest.raises(ValueError, match=r"'channel' can only be 'ibm_cloud', or 'ibm_quantum_platform"):
            IBMServerlessClient(channel=use_channel, instance=use_instance, token=use_token)

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_channel_defaults_to_ibm_quantum_platform_when_none(self, mock_file_path, mock_verify, mock_list_instances):
        """Test that channel defaults to IBM_QUANTUM_PLATFORM when None is provided."""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "test_instance",
                "plan": "test_plan",
                "name": "test_instance",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            }
        ]

        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(
                token="test_token", instance="test_instance", channel=None  # Explicitly pass None
            )

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_channel_defaults_to_ibm_quantum_platform_when_omitted(
        self, mock_file_path, mock_verify, mock_list_instances
    ):
        """Test that channel defaults to IBM_QUANTUM_PLATFORM when omitted."""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "test_instance",
                "plan": "test_plan",
                "name": "test_instance",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            }
        ]

        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(
                token="test_token",
                instance="test_instance",
                # channel parameter omitted
            )

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_channel_respects_explicit_ibm_cloud_value(self, mock_file_path, mock_verify, mock_list_instances):
        """Test that explicitly provided IBM_CLOUD channel is preserved."""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "test_instance",
                "plan": "test_plan",
                "name": "test_instance",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            }
        ]

        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            client = IBMServerlessClient(token="test_token", instance="test_instance", channel="ibm_cloud")

            assert client.channel == Channel.IBM_CLOUD.value
            assert client.account.channel == Channel.IBM_CLOUD.value

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_backward_compatibility_with_explicit_ibm_quantum_platform(
        self, mock_file_path, mock_verify, mock_list_instances
    ):
        """Test backward compatibility when IBM_QUANTUM_PLATFORM is explicitly provided."""

        # Mock list of instance crns in the IBM Cloud Global
        mock_list_instances.return_value = [
            {
                "crn": "test_instance",
                "plan": "test_plan",
                "name": "test_instance",
                "tags": "test_tags",
                "pricing_type": "test_pricing_type",
            }
        ]

        mock_verify.return_value = None

        with tempfile.NamedTemporaryFile() as temp_file:
            mock_file_path.return_value = temp_file.name

            # This is how users might have been calling it before
            client = IBMServerlessClient(token="test_token", instance="test_instance", channel="ibm_quantum_platform")

            assert client.channel == Channel.IBM_QUANTUM_PLATFORM.value
            assert client.account.channel == Channel.IBM_QUANTUM_PLATFORM.value


# ---------------------------------------------------------------------------
# Tests for backends()
# ---------------------------------------------------------------------------


class TestIBMServerlessClientBackends:
    """Tests for IBMServerlessClient.backends() and the backend cache."""

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_backends_returns_list_and_warms_cache(self, mock_file_path, mock_verify, mock_list_instances):
        """backends() delegates to service.backends() and populates _backends_cache."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)

        fake_b1 = MagicMock()
        fake_b1.name = "ibm_torino"
        fake_b2 = MagicMock()
        fake_b2.name = "ibm_brussels"
        client._service.backends = MagicMock(return_value=[fake_b1, fake_b2])  # mocking QiskitRuntimeService.backends

        result = client.backends()

        assert result == [fake_b1, fake_b2]
        # Cache should be populated for both backends
        assert client._backends_cache["ibm_torino"] is fake_b1
        assert client._backends_cache["ibm_brussels"] is fake_b2
        # Called with the client's instance so the listing is properly scoped
        client._service.backends.assert_called_once_with(instance="test_instance")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_backends_refresh_cache(self, mock_file_path, mock_verify, mock_list_instances):
        """backends() refresh cached backends as expected."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)

        fake_b1 = MagicMock()
        fake_b1.name = "ibm_torino"
        client._service.backends = MagicMock(return_value=[fake_b1])  # mocking QiskitRuntimeService.backends

        result = client.backends()

        assert result == [fake_b1]
        # Cache should be populated with backend
        assert client._backends_cache["ibm_torino"] is fake_b1

        # Now changing available backends
        fake_b2 = MagicMock()
        fake_b2.name = "ibm_brussels"
        client._service.backends = MagicMock(return_value=[fake_b2])
        assert result == [fake_b2]

        # Cache should be populated with backend
        assert client._backends_cache["ibm_brussels"] is fake_b2
        # Cache should be refreshed
        assert client._backends_cache.get("ibm_torino", None) is None

        # Called with the client's instance so the listing is properly scoped
        client._service.backends.assert_called_once_with(instance="test_instance")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_backends_passes_kwargs(self, mock_file_path, mock_verify, mock_list_instances):
        """Extra kwargs are forwarded verbatim to service.backends()."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backends = MagicMock(return_value=[])

        client.backends(min_num_qubits=127, operational=True)

        client._service.backends.assert_called_once_with(instance="test_instance", min_num_qubits=127, operational=True)

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_backends_wraps_exception(self, mock_file_path, mock_verify, mock_list_instances):
        """A failure from service.backends() is re-raised as QiskitServerlessException."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backends = MagicMock(side_effect=RuntimeError("network error"))

        with pytest.raises(QiskitServerlessException, match="Failed to retrieve backends"):
            client.backends()

# ---------------------------------------------------------------------------
# Tests for _get_backend()
# ---------------------------------------------------------------------------


class TestIBMServerlessClientGetBackend:
    """Tests for IBMServerlessClient._get_backend() — the per-run access check helper."""

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_get_backend_fetches_and_caches(self, mock_file_path, mock_verify, mock_list_instances):
        """_get_backend() calls service.backend(name) and stores the result in cache."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        fake_backend = MagicMock()
        client._service.backend = MagicMock(return_value=fake_backend)

        assert client._backends_cache == {}  # cache is empty on initialization

        result = client._get_backend("ibm_torino")

        assert result is fake_backend
        assert client._backends_cache["ibm_torino"] is fake_backend
        client._service.backend.assert_called_once_with("ibm_torino")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_get_backend_refreshes_on_cache_hit(self, mock_file_path, mock_verify, mock_list_instances):
        """Even when the name is already cached, service.backend() is still called to confirm
        that access has not been revoked since the cache was last written."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        stale_backend = MagicMock()
        stale_backend.name = "ibm_torino"
        client._backends_cache["ibm_torino"] = stale_backend  # seed cache

        fresh_backend = MagicMock()
        fresh_backend.name = "ibm_torino"
        client._service.backend = MagicMock(return_value=fresh_backend)

        result = client._get_backend("ibm_torino")

        # Returns the freshly fetched object, not the stale cached one
        assert result is fresh_backend
        # Cache is updated with the fresh object
        assert client._backends_cache["ibm_torino"] is fresh_backend
        client._service.backend.assert_called_once_with("ibm_torino")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_get_backend_raises_on_not_found(self, mock_file_path, mock_verify, mock_list_instances):
        """QiskitBackendNotFoundError is converted to QiskitServerlessException with a clear
        message that mentions the backend name and instance."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backend = MagicMock(side_effect=QiskitBackendNotFoundError("not found"))

        with pytest.raises(
            QiskitServerlessException,
            match="Backend 'nope' is not available or you do not have access",
        ):
            client._get_backend("nope")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_get_backend_wraps_generic_exception(self, mock_file_path, mock_verify, mock_list_instances):
        """Other exceptions from service.backend() are wrapped in QiskitServerlessException."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backend = MagicMock(side_effect=RuntimeError("timeout"))

        with pytest.raises(QiskitServerlessException, match="Failed to retrieve backend 'ibm_torino'"):
            client._get_backend("ibm_torino")


# ---------------------------------------------------------------------------
# Tests for _check_usage()
# ---------------------------------------------------------------------------


class TestIBMServerlessClientCheckUsage:
    """Tests for IBMServerlessClient._check_usage() — the usage quota pre-flight."""

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_unlimited_plan_no_action(self, mock_file_path, mock_verify, mock_list_instances):
        """When usage() returns no remaining-seconds key, the plan is unlimited → no warn/raise."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.usage = MagicMock(return_value={})  # no quota keys → unlimited

        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning would fail this test
            client._check_usage()  # should complete without raising or warning

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_raises_when_zero(self, mock_file_path, mock_verify, mock_list_instances):
        """remaining_seconds <= USAGE_ZERO_EPSILON_SECONDS → QiskitServerlessException."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        remaining_usage_seconds = float(USAGE_ZERO_EPSILON_SECONDS)/2 # below epsilon
        client._service.usage = MagicMock(return_value={"usage_remaining_seconds": remaining_usage_seconds})

        with pytest.raises(
            QiskitServerlessException,
            match="no remaining runtime quota",
        ):
            client._check_usage()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_raises_when_exactly_zero(self, mock_file_path, mock_verify, mock_list_instances):
        """remaining_seconds == 0 → error."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.usage = MagicMock(return_value={"usage_remaining_seconds": 0.0})

        with pytest.raises(QiskitServerlessException, match="no remaining runtime quota"):
            client._check_usage()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_warns_when_low(self, mock_file_path, mock_verify, mock_list_instances):
        """remaining_seconds below USAGE_LOW_THRESHOLD_SECONDS → UserWarning."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        # if epsilon< low_threshold, their avg is greater than epsilon and smaller than low_threshold
        remaining_usage_seconds = (float(USAGE_LOW_THRESHOLD_SECONDS+USAGE_ZERO_EPSILON_SECONDS))/2
        client._service.usage = MagicMock(return_value={"usage_remaining_seconds": remaining_usage_seconds})

        with pytest.warns(UserWarning, match="low remaining runtime quota"):
            client._check_usage()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_no_warn_when_plenty_remaining(self, mock_file_path, mock_verify, mock_list_instances):
        """remaining_seconds well above threshold → no warning at all."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        remaining_usage_seconds = 3 * USAGE_LOW_THRESHOLD_SECONDS  # above threshold
        client._service.usage = MagicMock(return_value={"usage_remaining_seconds": remaining_usage_seconds})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            client._check_usage()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_limit_reached_with_no_remaining_key(self, mock_file_path, mock_verify, mock_list_instances):
        """usage_limit_reached=True but no remaining key → treated as zero → raises."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.usage = MagicMock(return_value={"usage_limit_reached": True})

        with pytest.raises(QiskitServerlessException, match="no remaining runtime quota"):
            client._check_usage()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_check_usage_service_error_warns_not_raises(self, mock_file_path, mock_verify, mock_list_instances):
        """A transient error from service.usage() emits a warning but does NOT block the run."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.usage = MagicMock(side_effect=RuntimeError("503 service unavailable"))

        with pytest.warns(UserWarning, match="Could not retrieve usage information"):
            client._check_usage()


# ---------------------------------------------------------------------------
# Tests for run() override — pre-flight integration
# ---------------------------------------------------------------------------


class TestIBMServerlessClientRun:
    """Tests for the IBMServerlessClient.run() override with pre-flight validations."""

    def _setup_client(self, mock_file_path, mock_verify, mock_list_instances):
        """Create a client and stub out usage so tests can focus on backend checks."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        # Unlimited plan by default — avoids usage errors in backend-focused tests
        client._service.usage = MagicMock(return_value={})
        return client

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient.run")
    def test_run_with_valid_backend_calls_super(self, mock_super_run, mock_file_path, mock_verify, mock_list_instances):
        """run(backend_name=X) validates the backend then delegates to ServerlessClient.run."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        fake_backend = MagicMock()
        client._service.backend = MagicMock(return_value=fake_backend)

        fake_job = MagicMock()
        mock_super_run.return_value = fake_job

        result = client.run("my_function", arguments={"backend_name": "ibm_torino"})

        client._service.backend.assert_called_once_with("ibm_torino")
        mock_super_run.assert_called_once()
        assert result is fake_job

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient.run")
    def test_run_does_not_call_full_backends_when_backend_name_given(
        self, mock_super_run, mock_file_path, mock_verify, mock_list_instances
    ):
        """When backend_name is supplied, run() must NOT trigger a full backends() listing.
        This ensures run() stays fast regardless of cache state."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backend = MagicMock(return_value=MagicMock())
        client._service.backends = MagicMock()  # should never be called
        mock_super_run.return_value = MagicMock()

        client.run("fn", arguments={"backend_name": "ibm_torino"})

        client._service.backends.assert_not_called()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_run_raises_when_backend_not_accessible(self, mock_file_path, mock_verify, mock_list_instances):
        """run(backend_name=X) raises QiskitServerlessException when backend is inaccessible."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backend = MagicMock(side_effect=QiskitBackendNotFoundError("not found"))

        with pytest.raises(
            QiskitServerlessException,
            match="not available or you do not have access",
        ):
            client.run("fn", arguments={"backend_name": "restricted_backend"})

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient.run")
    def test_run_without_backend_name_checks_instance_has_backends(
        self, mock_super_run, mock_file_path, mock_verify, mock_list_instances
    ):
        """When no backend_name is given, run() calls backends() to verify the instance is not
        empty, then proceeds to submit."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        fake_b = MagicMock()
        fake_b.name = "ibm_torino"
        client._service.backends = MagicMock(return_value=[fake_b])
        mock_super_run.return_value = MagicMock()

        client.run("fn")  # no backend_name

        client._service.backends.assert_called_once()
        mock_super_run.assert_called_once()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_run_raises_when_instance_has_no_backends(self, mock_file_path, mock_verify, mock_list_instances):
        """run() without backend_name raises when the instance returns an empty backends list."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backends = MagicMock(return_value=[])

        with pytest.raises(
            QiskitServerlessException,
            match="has no backends available",
        ):
            client.run("fn")

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    def test_run_raises_on_exhausted_quota(self, mock_file_path, mock_verify, mock_list_instances):
        """run() raises before touching backend checks when usage quota is exhausted."""
        client = _make_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.usage = MagicMock(return_value={"usage_remaining_seconds": 0.0})
        # backend mock should never be reached
        client._service.backend = MagicMock()

        with pytest.raises(QiskitServerlessException, match="no remaining runtime quota"):
            client.run("fn", arguments={"backend_name": "ibm_torino"})

        client._service.backend.assert_not_called()

    @patch(_LIST_INSTANCES)
    @patch(_VERIFY_CREDS)
    @patch(_CONFIG_FILE)
    @patch("qiskit_serverless.core.clients.serverless_client.ServerlessClient.run")
    def test_run_cache_used_across_repeated_calls(
        self, mock_super_run, mock_file_path, mock_verify, mock_list_instances
    ):
        """Repeated run() calls for the same backend each call service.backend() once to
        refresh access, but never trigger a full backends() listing."""
        client = self._setup_client(mock_file_path, mock_verify, mock_list_instances)
        client._service.backend = MagicMock(return_value=MagicMock())
        client._service.backends = MagicMock()
        mock_super_run.return_value = MagicMock()

        client.run("fn", arguments={"backend_name": "ibm_torino"})
        client.run("fn", arguments={"backend_name": "ibm_torino"})
        client.run("fn", arguments={"backend_name": "ibm_torino"})

        # service.backend called once per run (refresh on each hit, per spec)
        assert client._service.backend.call_count == 3
        # Full listing never called
        client._service.backends.assert_not_called()
