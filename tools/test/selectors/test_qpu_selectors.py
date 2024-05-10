"""Tests for QPU selectors."""

from unittest import TestCase
from unittest.mock import MagicMock

from qiskit import QuantumCircuit
from qiskit.providers.fake_provider import FakeHanoi
from qiskit_ibm_runtime import Session

from qiskit_serverless_tools.selectors import IBMLeastBusyQPUSelector, IBMLeastNoisyQPUSelector


def _get_mock_backend(backend_name):
    return FakeHanoi()


def _get_mock_backends(min_num_qubits, filters=None):
    return [FakeHanoi()]


def _get_mock_least_busy_backend(min_num_qubits, filters=None):
    mock_backend = MagicMock(num_qubits=27)
    mock_backend.name = "mock_backend"

    return mock_backend


class TestBackendSelectors(TestCase):
    """TestBackendSelectors"""

    def setUp(self):
        self.mock_service = MagicMock(
            least_busy=_get_mock_least_busy_backend,
            backends=_get_mock_backends,
            get_backend=_get_mock_backend,
        )

    def test_least_busy(self):
        """Tests least busy selector."""
        selector = IBMLeastBusyQPUSelector(self.mock_service)
        backend = selector.get_backend(min_num_qubits=5)
        session = selector.get_session(min_num_qubits=5)

        self.assertEqual(backend.name, "mock_backend")
        self.assertEqual(backend.num_qubits, 27)
        self.assertIsInstance(session, Session)
        self.assertEqual(session.backend().name, "mock_backend")

    def test_least_noisy(self):
        """Tests least noisy selector."""
        qc = QuantumCircuit(8)
        qc.h(0)
        for a in range(qc.num_qubits - 1):
            qc.cx(a, a + 1)
        selector = IBMLeastNoisyQPUSelector(self.mock_service, circuit=qc)
        backend = selector.get_backend(min_num_qubits=8)
        session = selector.get_session(min_num_qubits=8)

        self.assertEqual(backend.name(), "fake_hanoi")
        self.assertEqual(len(backend.properties().qubits), 27)
        self.assertIsInstance(session, Session)
        self.assertEqual(session.backend().name(), "fake_hanoi")
