# source_files/pattern_with_runtime_wrapper.py

import os
from qiskit_serverless import save_result, ServerlessRuntimeService

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2

service = ServerlessRuntimeService(
    channel=os.environ["QISKIT_IBM_CHANNEL"],
    instance=os.environ["QISKIT_IBM_INSTANCE"],
    token=os.environ["QISKIT_IBM_TOKEN"],
    url="https://test.cloud.ibm.com",
)

backends = service.backends()
backend = service.backend("test_eagle")
sampler = SamplerV2(backend)

qc = QuantumCircuit(1)
qc.measure_all()
out1 = sampler.run([qc])
out2 = sampler.run([qc])

save_result(
    {
        "backends": backends,
        "results": [out1.job_id, out2.job_id],
    }
)
