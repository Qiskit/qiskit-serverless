"""Qiskit Function code that instantiates a service with 
get_runtime_service and submits 2 jobs within 2 sessions."""

# pylint: disable=duplicate-code

import warnings
import os

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2, Session

from qiskit_serverless import save_result, get_runtime_service

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

service = get_runtime_service(url=os.environ["QISKIT_IBM_URL_STAGING"])

backends = service.backends()
backend1 = service.backend("test_eagle")
backend2 = service.backend("test_eagle2")

qc = QuantumCircuit(1)
qc.measure_all()

job_ids = []
session_ids = []

for backend in [backend1, backend2]:
    session = Session(backend=backend)
    sampler = SamplerV2(mode=session)

    job1 = sampler.run([qc])
    job2 = sampler.run([qc])

    job_ids += [job1.job_id(), job2.job_id()]
    session_ids.append(session.session_id)


save_result(
    {
        "backends": [back.name for back in backends],
        "results": [
            job_ids,
            session_ids,
        ],
    }
)
