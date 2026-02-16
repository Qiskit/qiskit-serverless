"""Runtime monkeypatches for external tests.

If QISKIT_IBM_URL points to a mock URL, patch qiskit_ibm_runtime primitives
to avoid real network calls while preserving runtime-wrapper behavior.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse


def _is_mock_runtime_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme == "mock":
        return True
    return "mock-runtime" in url


if _is_mock_runtime_url(os.environ.get("QISKIT_IBM_URL", "")):
    # Import only when patching is needed.
    import qiskit_ibm_runtime as _runtime
    import qiskit_ibm_runtime.runtime_job_v2 as _runtime_job_v2

    class _Backend:
        def __init__(self, name: str, service):
            self.name = name
            self._service = service

    class _RuntimeJobV2:
        def __init__(self, job_id: str, session_id=None):
            self._job_id = job_id
            self.session_id = session_id

        def job_id(self):
            return self._job_id

        def result(self):
            return {"status": "done"}

    class _QiskitRuntimeService:
        def __init__(self, *args, **kwargs):
            self._backends = {
                "test_eagle": _Backend("test_eagle", self),
                "test_eagle2": _Backend("test_eagle2", self),
            }

        def backends(self):
            return list(self._backends.values())

        def backend(self, name: str):
            return self._backends[name]

        def _run(self, program_id: str, inputs: dict, *args, **kwargs):
            session_id = kwargs.get("session_id")
            return _RuntimeJobV2(
                job_id=f"mock-runtime-job-{uuid.uuid4().hex}",
                session_id=session_id,
            )

    class _Session:
        def __init__(self, backend):
            self.backend = backend
            self.session_id = f"mock-session-{uuid.uuid4().hex}"

    class _SamplerV2:
        def __init__(self, backend=None, mode=None):
            self._backend = backend
            self._session = mode

        def run(self, circuits):
            if self._session is not None:
                service = self._session.backend._service
                return service._run(
                    program_id="sampler",
                    inputs={"circuits": circuits},
                    session_id=self._session.session_id,
                )

            service = self._backend._service
            return service._run(
                program_id="sampler",
                inputs={"circuits": circuits},
            )

    _runtime.QiskitRuntimeService = _QiskitRuntimeService
    _runtime.Session = _Session
    _runtime.SamplerV2 = _SamplerV2
    _runtime_job_v2.RuntimeJobV2 = _RuntimeJobV2
