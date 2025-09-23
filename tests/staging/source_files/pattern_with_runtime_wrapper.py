# source_files/pattern_with_runtime_wrapper.py

import os
import warnings
from qiskit_serverless import save_result, ServerlessRuntimeService

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2

# from qiskit_serverless.core.constants import (
#     ENV_JOB_GATEWAY_INSTANCE,
#     QISKIT_IBM_CHANNEL,
#     REQUESTS_TIMEOUT,
#     ENV_JOB_GATEWAY_TOKEN,
#     ENV_JOB_GATEWAY_HOST,
#     ENV_JOB_ID_GATEWAY,
#     ENV_GATEWAY_PROVIDER_VERSION,
#     GATEWAY_PROVIDER_VERSION_DEFAULT,
# )

# from qiskit_serverless.utils.http import get_headers

import logging
import requests


# def associate_runtime_job_with_serverless_job(
#     runtime_job_id: str, session_id=None
# ) -> bool:
#     """Make a request to gateway to associate runtime job id with serverless job id.

#     Args:
#         runtime_job_id (str): job id for runtime primitive
#         session_id (str): session/batch id

#     Returns:
#         bool: if request was ok
#     """
#     version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
#     if version is None:
#         version = GATEWAY_PROVIDER_VERSION_DEFAULT

#     token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
#     if token is None:
#         logging.warning("Runtime job will not be associated with serverless job.")
#         return False

#     instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)
#     channel = os.environ.get(QISKIT_IBM_CHANNEL, None)

#     url = (
#         f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
#         f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/runtime_jobs/"
#     )
#     message_1 = f"Inside associate {runtime_job_id} with serverless job. {url}"

#     response = requests.post(
#         url,
#         json={"runtime_job": runtime_job_id, "runtime_session": session_id},
#         headers=get_headers(token=token, instance=instance, channel=channel),
#         timeout=REQUESTS_TIMEOUT,
#     )
#     print(f"RESPONSE: {response.ok}")
#     if not response.ok:
#         sanitized = response.text.replace("\n", "").replace("\r", "")
#         logging.warning("Something went wrong: %s", sanitized)
#     print(f"SUCCESS!! Runtime job {runtime_job_id} associated with serverless job.")
#     message_2 = (
#         f"SUCCESS!! Runtime job {runtime_job_id} associated with serverless job."
#     )

#     return [response.ok, message_1, message_2]


warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

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

job_id_1 = out1.job_id()
job_id_2 = out2.job_id()

# print(
#     "outside associate ok??",
#     associate_runtime_job_with_serverless_job(job_id_1, ""),
# )

print("JOB IDS:", out1.job_id(), out2.job_id())
# print("RESULT 1:", out1.result())
# print("RESULT 2:", out2.result())

save_result(
    {
        "backends": [back.name for back in backends],
        "results": [out1.job_id(), out2.job_id()],
    }
)
