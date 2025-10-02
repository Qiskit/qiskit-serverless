# source_files/pattern_with_runtime_wrapper_2.py

import warnings
import os

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2, Session, QiskitRuntimeService

from qiskit_serverless import save_result

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

service = QiskitRuntimeService(
    channel=os.environ["QISKIT_IBM_CHANNEL"],
    instance=os.environ["QISKIT_IBM_INSTANCE"],
    token=os.environ["QISKIT_IBM_TOKEN"],
    url="https://test.cloud.ibm.com",
)

backends = service.backends()
backend = service.backend("ibm_genova")
session = Session(backend=backend)
sampler = SamplerV2(mode=session)

qc = QuantumCircuit(1)
qc.measure_all()
out1 = sampler.run([qc])
out2 = sampler.run([qc])

job_id_1 = out1.job_id()
job_id_2 = out2.job_id()


save_result(
    {
        "backends": [back.name for back in backends],
        "results": [
            [out1.job_id(), session.session_id],
            [out2.job_id(), session.session_id],
        ],
    }
)
