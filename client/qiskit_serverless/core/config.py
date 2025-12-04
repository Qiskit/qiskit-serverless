"""Centralized configuration for environment variables."""

import os
from typing import Optional

from qiskit_serverless.core.constants import (
    DATA_PATH,
    DATA_PATH_DEFAULT,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_GATEWAY_PROVIDER_TOKEN,
    ENV_GATEWAY_PROVIDER_VERSION,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_GATEWAY_INSTANCE,
    ENV_JOB_ID_GATEWAY,
    ENV_JOB_GATEWAY_TOKEN,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    ENV_ACCESS_TRIAL,
    IBM_SERVERLESS_HOST_URL_DEFAULT,
    IBM_SERVERLESS_HOST_URL_OVERRIDE,
    MAX_ARTIFACT_FILE_SIZE_MB_DEFAULT,
    MAX_ARTIFACT_FILE_SIZE_MB_OVERRIDE,
    OT_ENABLED,
    OT_INSECURE,
    OT_JAEGER_HOST_KEY,
    OT_JAEGER_PORT_KEY,
    OT_PROGRAM_NAME,
    OT_PROGRAM_NAME_DEFAULT,
    OT_RAY_TRACER,
    OT_TRACEPARENT_ID_KEY,
    QISKIT_IBM_CHANNEL,
    QISKIT_IBM_INSTANCE,
    QISKIT_IBM_TOKEN,
    QISKIT_IBM_URL,
    REQUESTS_STREAMING_TIMEOUT_DEFAULT,
    REQUESTS_STREAMING_TIMEOUT_OVERRIDE,
    REQUESTS_TIMEOUT_DEFAULT,
    REQUESTS_TIMEOUT_OVERRIDE,
)


class Config:  # pylint: disable=too-many-public-methods
    """Centralized configuration for environment variables.

    This class provides type-safe access to environment variables with
    consistent default values across the codebase.
    """

    # Telemetry/Tracing Configuration
    @classmethod
    def ot_program_name(cls) -> str:
        """Get OpenTelemetry program name."""
        return os.environ.get(OT_PROGRAM_NAME, OT_PROGRAM_NAME_DEFAULT)

    @classmethod
    def ot_jaeger_host(cls) -> Optional[str]:
        """Get Jaeger host for tracing."""
        return os.environ.get(OT_JAEGER_HOST_KEY, None)

    @classmethod
    def ot_jaeger_port(cls) -> int:
        """Get Jaeger port for tracing."""
        return int(os.environ.get(OT_JAEGER_PORT_KEY, "6831"))

    @classmethod
    def ot_traceparent_id(cls) -> Optional[str]:
        """Get OpenTelemetry traceparent ID."""
        return os.environ.get(OT_TRACEPARENT_ID_KEY, None)

    @classmethod
    def ot_insecure(cls) -> bool:
        """Check if OpenTelemetry should use insecure connection."""
        return bool(int(os.environ.get(OT_INSECURE, "0")))

    @classmethod
    def ot_enabled(cls) -> bool:
        """Check if OpenTelemetry tracing is enabled."""
        return bool(int(os.environ.get(OT_ENABLED, "0")))

    @classmethod
    def ot_ray_tracer(cls) -> bool:
        """Check if Ray tracer is enabled."""
        return bool(int(os.environ.get(OT_RAY_TRACER, "0")))

    # Gateway Configuration
    @classmethod
    def gateway_host(cls) -> Optional[str]:
        """Get gateway provider host."""
        return os.environ.get(ENV_GATEWAY_PROVIDER_HOST, None)

    @classmethod
    def gateway_version(cls) -> str:
        """Get gateway provider version."""
        return os.environ.get(
            ENV_GATEWAY_PROVIDER_VERSION, GATEWAY_PROVIDER_VERSION_DEFAULT
        )

    @classmethod
    def gateway_provider_version(cls) -> str:
        """Get gateway provider version (alias for gateway_version)."""
        return cls.gateway_version()

    @classmethod
    def gateway_token(cls) -> Optional[str]:
        """Get gateway provider token."""
        return os.environ.get(ENV_GATEWAY_PROVIDER_TOKEN, None)

    # Job Configuration
    @classmethod
    def job_gateway_token(cls) -> Optional[str]:
        """Get job gateway token."""
        return os.environ.get(ENV_JOB_GATEWAY_TOKEN, None)

    @classmethod
    def job_gateway_instance(cls) -> Optional[str]:
        """Get job gateway instance."""
        return os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)

    @classmethod
    def job_gateway_host(cls) -> Optional[str]:
        """Get job gateway host."""
        return os.environ.get(ENV_JOB_GATEWAY_HOST, None)

    @classmethod
    def job_id_gateway(cls) -> Optional[str]:
        """Get job ID from gateway."""
        return os.environ.get(ENV_JOB_ID_GATEWAY, None)

    @classmethod
    def qiskit_ibm_channel(cls) -> Optional[str]:
        """Get Qiskit IBM channel."""
        return os.environ.get(QISKIT_IBM_CHANNEL, None)

    @classmethod
    def qiskit_ibm_token(cls) -> Optional[str]:
        """Get Qiskit IBM token."""
        return os.environ.get(QISKIT_IBM_TOKEN, None)

    @classmethod
    def qiskit_ibm_url(cls) -> Optional[str]:
        """Get Qiskit IBM URL."""
        return os.environ.get(QISKIT_IBM_URL, None)

    @classmethod
    def qiskit_ibm_instance(cls) -> Optional[str]:
        """Get Qiskit IBM instance."""
        return os.environ.get(QISKIT_IBM_INSTANCE, None)

    # Data Configuration
    @classmethod
    def data_path(cls) -> str:
        """Get data path."""
        return os.environ.get(DATA_PATH, DATA_PATH_DEFAULT)

    # Request Configuration
    @classmethod
    def requests_timeout(cls) -> int:
        """Get request timeout in seconds."""
        return int(
            os.environ.get(REQUESTS_TIMEOUT_OVERRIDE, str(REQUESTS_TIMEOUT_DEFAULT))
        )

    @classmethod
    def requests_streaming_timeout(cls) -> int:
        """Get streaming request timeout in seconds."""
        return int(
            os.environ.get(
                REQUESTS_STREAMING_TIMEOUT_OVERRIDE,
                str(REQUESTS_STREAMING_TIMEOUT_DEFAULT),
            )
        )

    # Artifact Configuration
    @classmethod
    def max_artifact_file_size_mb(cls) -> int:
        """Get maximum artifact file size in MB."""
        return int(
            os.environ.get(
                MAX_ARTIFACT_FILE_SIZE_MB_OVERRIDE,
                str(MAX_ARTIFACT_FILE_SIZE_MB_DEFAULT),
            )
        )

    # IBM Serverless Configuration
    @classmethod
    def ibm_serverless_host_url(cls) -> str:
        """Get IBM Serverless host URL."""
        return os.environ.get(
            IBM_SERVERLESS_HOST_URL_OVERRIDE, IBM_SERVERLESS_HOST_URL_DEFAULT
        )

    # Access Configuration
    @classmethod
    def is_trial(cls) -> bool:
        """Check if running in trial mode."""
        return os.environ.get(ENV_ACCESS_TRIAL) == "True"

    # Test Configuration
    @classmethod
    def in_test(cls) -> Optional[str]:
        """Check if running in test mode."""
        return os.environ.get("IN_TEST")
