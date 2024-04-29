"""Constants."""

import os

META_TOPIC: str = "execution-meta"

QS_EXECUTION_WORKLOAD_ID: str = "QS_EXECUTION_WORKLOAD_ID"
QS_EXECUTION_UID: str = "QS_EXECUTION_UID"

# telemetry
OT_PROGRAM_NAME = "OT_PROGRAM_NAME"
OT_PROGRAM_NAME_DEFAULT = "unnamed_execution"
OT_JAEGER_HOST = "OT_JAEGER_HOST"
OT_JAEGER_HOST_KEY = "OT_JAEGER_HOST_KEY"
OT_JAEGER_PORT_KEY = "OT_JAEGER_PORT_KEY"
OT_TRACEPARENT_ID_KEY = "OT_TRACEPARENT_ID_KEY"
OT_INSECURE = "OT_INSECURE"
OT_ENABLED = "OT_ENABLED"
OT_RAY_TRACER = "TO_RAY_TRACER"
OT_SPAN_DEFAULT_NAME = "entrypoint"
OT_ATTRIBUTE_PREFIX = "qs"
OT_LABEL_CALL_LOCATION = "qs.location"

# request timeout
REQUESTS_TIMEOUT: int = 30
REQUESTS_TIMEOUT_OVERRIDE = "REQUESTS_TIMEOUT_OVERRIDE"

# gateway
ENV_GATEWAY_PROVIDER_HOST = "ENV_GATEWAY_PROVIDER_HOST"
ENV_GATEWAY_PROVIDER_VERSION = "ENV_GATEWAY_PROVIDER_VERSION"
ENV_GATEWAY_PROVIDER_TOKEN = "ENV_GATEWAY_PROVIDER_TOKEN"
GATEWAY_PROVIDER_VERSION_DEFAULT = "v1"

# auth
ENV_JOB_GATEWAY_TOKEN = "ENV_JOB_GATEWAY_TOKEN"
ENV_JOB_GATEWAY_HOST = "ENV_JOB_GATEWAY_HOST"
ENV_JOB_ID_GATEWAY = "ENV_JOB_ID_GATEWAY"
ENV_JOB_ARGUMENTS = "ENV_JOB_ARGUMENTS"

# artifact
MAX_ARTIFACT_FILE_SIZE_MB = 50
MAX_ARTIFACT_FILE_SIZE_MB_OVERRIDE = "MAX_ARTIFACT_FILE_SIZE_MB_OVERRIDE"

# IBM urls
IBM_SERVERLESS_HOST_URL = "https://middleware.quantum-computing.ibm.com"
IBM_SERVERLESS_HOST_URL_OVERRIDE = "IBM_SERVERLESS_HOST_URL_OVERRIDE"

REQUESTS_TIMEOUT = int(
    os.getenv(REQUESTS_TIMEOUT_OVERRIDE, default=str(REQUESTS_TIMEOUT))
)
MAX_ARTIFACT_FILE_SIZE_MB = int(
    os.getenv(
        MAX_ARTIFACT_FILE_SIZE_MB_OVERRIDE, default=str(MAX_ARTIFACT_FILE_SIZE_MB)
    )
)
IBM_SERVERLESS_HOST_URL = os.getenv(
    IBM_SERVERLESS_HOST_URL_OVERRIDE, default=IBM_SERVERLESS_HOST_URL
)
