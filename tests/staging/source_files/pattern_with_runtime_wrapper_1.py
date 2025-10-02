# source_files/pattern_with_runtime_wrapper.py

import warnings

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2

from qiskit_serverless import save_result, get_runtime_service

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

service = get_runtime_service(url="https://test.cloud.ibm.com")

backends = service.backends()
backend = service.backend("test_eagle")
sampler = SamplerV2(backend)

qc = QuantumCircuit(1)
qc.measure_all()
out1 = sampler.run([qc])
out2 = sampler.run([qc])

job_id_1 = out1.job_id()
job_id_2 = out2.job_id()

print("JOB IDS: ", out1.job_id(), out2.job_id())
print("BACKENDS: ", [back.name for back in backends])
print("RESULTS: ", [out1.job_id(), out2.job_id()])
save_result(
    {
        "backends": [back.name for back in backends],
        "results": [out1.job_id(), out2.job_id()],
    }
)
