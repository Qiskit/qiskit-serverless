"""Centralized configuration for environment variables."""

import os
from typing import List, Optional

from constants import (
    ALLOWED_HOSTS,
    ALLOWED_HOSTS_DEFAULT,
    CORS_ALLOWED_ORIGIN_REGEXES,
    CORS_ALLOWED_ORIGIN_REGEXES_DEFAULT,
    CSRF_TRUSTED_ORIGINS,
    CSRF_TRUSTED_ORIGINS_DEFAULT,
    CUSTOM_IMAGE_PACKAGE_NAME,
    CUSTOM_IMAGE_PACKAGE_NAME_DEFAULT,
    CUSTOM_IMAGE_PACKAGE_PATH,
    CUSTOM_IMAGE_PACKAGE_PATH_DEFAULT,
    DATABASE_HOST,
    DATABASE_HOST_DEFAULT,
    DATABASE_NAME,
    DATABASE_NAME_DEFAULT,
    DATABASE_PASSWORD,
    DATABASE_PASSWORD_DEFAULT,
    DATABASE_PORT,
    DATABASE_PORT_DEFAULT,
    DATABASE_USER,
    DATABASE_USER_DEFAULT,
    DEBUG,
    DEBUG_DEFAULT,
    DJANGO_SECRET_KEY,
    DJANGO_SECRET_KEY_DEFAULT,
    FUNCTIONS_LOGS_SIZE_LIMIT,
    FUNCTIONS_LOGS_SIZE_LIMIT_DEFAULT,
    GATEWAY_ALLOWLIST_CONFIG,
    GATEWAY_ALLOWLIST_CONFIG_DEFAULT,
    GATEWAY_DYNAMIC_DEPENDENCIES,
    GATEWAY_DYNAMIC_DEPENDENCIES_DEFAULT,
    GATEWAY_GPU_JOBS_CONFIG,
    GATEWAY_GPU_JOBS_CONFIG_DEFAULT,
    IAM_IBM_CLOUD_BASE_URL,
    IQP_QCON_API_BASE_URL,
    LIMITS_CPU_PER_TASK,
    LIMITS_CPU_PER_TASK_DEFAULT,
    LIMITS_GPU_PER_TASK,
    LIMITS_GPU_PER_TASK_DEFAULT,
    LIMITS_JOBS_PER_USER,
    LIMITS_JOBS_PER_USER_DEFAULT,
    LIMITS_MAX_CLUSTERS,
    LIMITS_MAX_CLUSTERS_DEFAULT,
    LIMITS_MAX_GPU_CLUSTERS,
    LIMITS_MAX_GPU_CLUSTERS_DEFAULT,
    LIMITS_MEMORY_PER_TASK,
    LIMITS_MEMORY_PER_TASK_DEFAULT,
    MAINTENANCE,
    PROGRAM_TIMEOUT,
    PROGRAM_TIMEOUT_DEFAULT,
    QISKIT_IBM_URL,
    QISKIT_IBM_URL_DEFAULT,
    QUANTUM_PLATFORM_API_BASE_URL,
    RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL,
    RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL_DEFAULT,
    RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL,
    RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL_DEFAULT,
    RAY_CLUSTER_MAX_READINESS_TIME,
    RAY_CLUSTER_MAX_READINESS_TIME_DEFAULT,
    RAY_CLUSTER_MODE_LOCAL,
    RAY_CLUSTER_MODE_LOCAL_DEFAULT,
    RAY_CLUSTER_MODE_LOCAL_HOST,
    RAY_CLUSTER_MODE_LOCAL_HOST_DEFAULT,
    RAY_CLUSTER_NO_DELETE_ON_COMPLETE,
    RAY_CLUSTER_WORKER_AUTO_SCALING,
    RAY_CLUSTER_WORKER_MAX_REPLICAS,
    RAY_CLUSTER_WORKER_MAX_REPLICAS_DEFAULT,
    RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX,
    RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX_DEFAULT,
    RAY_CLUSTER_WORKER_MIN_REPLICAS,
    RAY_CLUSTER_WORKER_MIN_REPLICAS_DEFAULT,
    RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX,
    RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX_DEFAULT,
    RAY_CLUSTER_WORKER_REPLICAS,
    RAY_CLUSTER_WORKER_REPLICAS_DEFAULT,
    RAY_CLUSTER_WORKER_REPLICAS_MAX,
    RAY_CLUSTER_WORKER_REPLICAS_MAX_DEFAULT,
    RAY_KUBERAY_NAMESPACE,
    RAY_KUBERAY_NAMESPACE_DEFAULT,
    RAY_NODE_IMAGE,
    RAY_NODE_IMAGE_DEFAULT,
    RAY_SETUP_MAX_RETRIES,
    RAY_SETUP_MAX_RETRIES_DEFAULT,
    RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL,
    RESOURCE_PLANS_ID_ALLOWED,
    SETTINGS_AUTH_MECHANISM,
    SETTINGS_AUTH_MECHANISM_DEFAULT,
    SETTINGS_AUTH_MOCK_TOKEN,
    SETTINGS_AUTH_MOCK_TOKEN_DEFAULT,
    SETTINGS_AUTH_MOCKPROVIDER_REGISTRY,
    SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD,
    SITE_HOST,
    SITE_HOST_DEFAULT,
    VERSION,
    VERSION_DEFAULT,
)


class Config:
    """Centralized configuration for environment variables."""

    # Version and Debug
    @classmethod
    def version(cls) -> str:
        """Get release version."""
        return os.environ.get(VERSION, VERSION_DEFAULT)

    @classmethod
    def debug(cls) -> int:
        """Check if debug mode is enabled."""
        return int(os.environ.get(DEBUG, DEBUG_DEFAULT))

    @classmethod
    def log_level(cls) -> str:
        """Get log level based on debug setting."""
        return "DEBUG" if cls.debug() else "INFO"

    # Security
    @classmethod
    def secret_key(cls) -> str:
        """Get Django secret key."""
        return os.environ.get(DJANGO_SECRET_KEY, DJANGO_SECRET_KEY_DEFAULT)

    @classmethod
    def allowed_hosts(cls) -> List[str]:
        """Get allowed hosts."""
        return os.environ.get(ALLOWED_HOSTS, ALLOWED_HOSTS_DEFAULT).split(",")

    @classmethod
    def csrf_trusted_origins(cls) -> List[str]:
        """Get CSRF trusted origins."""
        return os.environ.get(CSRF_TRUSTED_ORIGINS, CSRF_TRUSTED_ORIGINS_DEFAULT).split(
            ","
        )

    @classmethod
    def cors_allowed_origin_regexes(cls) -> List[str]:
        """Get CORS allowed origin regexes."""
        patterns = os.environ.get(
            CORS_ALLOWED_ORIGIN_REGEXES, CORS_ALLOWED_ORIGIN_REGEXES_DEFAULT
        ).split(",")
        return [rf"{pattern}" for pattern in patterns]

    # Database
    @classmethod
    def database_name(cls) -> str:
        """Get database name."""
        return os.environ.get(DATABASE_NAME, DATABASE_NAME_DEFAULT)

    @classmethod
    def database_user(cls) -> str:
        """Get database user."""
        return os.environ.get(DATABASE_USER, DATABASE_USER_DEFAULT)

    @classmethod
    def database_password(cls) -> str:
        """Get database password."""
        return os.environ.get(DATABASE_PASSWORD, DATABASE_PASSWORD_DEFAULT)

    @classmethod
    def database_host(cls) -> str:
        """Get database host."""
        return os.environ.get(DATABASE_HOST, DATABASE_HOST_DEFAULT)

    @classmethod
    def database_port(cls) -> str:
        """Get database port."""
        return os.environ.get(DATABASE_PORT, DATABASE_PORT_DEFAULT)

    # Authentication
    @classmethod
    def auth_mechanism(cls) -> str:
        """Get authentication mechanism."""
        return os.environ.get(SETTINGS_AUTH_MECHANISM, SETTINGS_AUTH_MECHANISM_DEFAULT)

    @classmethod
    def auth_mock_token(cls) -> str:
        """Get mock authentication token."""
        return os.environ.get(
            SETTINGS_AUTH_MOCK_TOKEN, SETTINGS_AUTH_MOCK_TOKEN_DEFAULT
        )

    @classmethod
    def auth_mockprovider_registry(cls) -> Optional[str]:
        """Get mock provider registry."""
        return os.environ.get(SETTINGS_AUTH_MOCKPROVIDER_REGISTRY, None)

    @classmethod
    def quantum_platform_api_base_url(cls) -> Optional[str]:
        """Get Quantum Platform API base URL."""
        return os.environ.get(QUANTUM_PLATFORM_API_BASE_URL, None)

    @classmethod
    def token_auth_verification_field(cls) -> Optional[str]:
        """Get token authentication verification field."""
        return os.environ.get(SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD, None)

    # Site
    @classmethod
    def site_host(cls) -> str:
        """Get site host."""
        return os.environ.get(SITE_HOST, SITE_HOST_DEFAULT)

    # Resource Limits
    @classmethod
    def limits_jobs_per_user(cls) -> int:
        """Get maximum jobs per user."""
        return int(os.environ.get(LIMITS_JOBS_PER_USER, LIMITS_JOBS_PER_USER_DEFAULT))

    @classmethod
    def limits_max_clusters(cls) -> int:
        """Get maximum clusters."""
        return int(os.environ.get(LIMITS_MAX_CLUSTERS, LIMITS_MAX_CLUSTERS_DEFAULT))

    @classmethod
    def limits_gpu_clusters(cls) -> int:
        """Get maximum GPU clusters."""
        return int(
            os.environ.get(LIMITS_MAX_GPU_CLUSTERS, LIMITS_MAX_GPU_CLUSTERS_DEFAULT)
        )

    @classmethod
    def limits_cpu_per_task(cls) -> int:
        """Get CPU limit per task."""
        return int(os.environ.get(LIMITS_CPU_PER_TASK, LIMITS_CPU_PER_TASK_DEFAULT))

    @classmethod
    def limits_gpu_per_task(cls) -> int:
        """Get GPU limit per task."""
        return int(os.environ.get(LIMITS_GPU_PER_TASK, LIMITS_GPU_PER_TASK_DEFAULT))

    @classmethod
    def limits_memory_per_task(cls) -> int:
        """Get memory limit per task."""
        return int(
            os.environ.get(LIMITS_MEMORY_PER_TASK, LIMITS_MEMORY_PER_TASK_DEFAULT)
        )

    @classmethod
    def maintenance(cls) -> bool:
        """Check if maintenance mode is enabled."""
        return os.environ.get(MAINTENANCE, "false") == "true"

    # Ray Cluster Configuration
    @classmethod
    def ray_kuberay_namespace(cls) -> str:
        """Get Ray KubeRay namespace."""
        return os.environ.get(RAY_KUBERAY_NAMESPACE, RAY_KUBERAY_NAMESPACE_DEFAULT)

    @classmethod
    def ray_cluster_mode_local(cls) -> int:
        """Get Ray cluster local mode setting."""
        return int(
            os.environ.get(RAY_CLUSTER_MODE_LOCAL, RAY_CLUSTER_MODE_LOCAL_DEFAULT)
        )

    @classmethod
    def ray_cluster_mode_local_host(cls) -> str:
        """Get Ray cluster local host."""
        return os.environ.get(
            RAY_CLUSTER_MODE_LOCAL_HOST, RAY_CLUSTER_MODE_LOCAL_HOST_DEFAULT
        )

    @classmethod
    def ray_node_image(cls) -> str:
        """Get Ray node image."""
        return os.environ.get(RAY_NODE_IMAGE, RAY_NODE_IMAGE_DEFAULT)

    @classmethod
    def ray_cluster_worker_replicas(cls) -> int:
        """Get Ray cluster worker replicas."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_REPLICAS, RAY_CLUSTER_WORKER_REPLICAS_DEFAULT
            )
        )

    @classmethod
    def ray_cluster_worker_replicas_max(cls) -> int:
        """Get Ray cluster worker replicas maximum."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_REPLICAS_MAX, RAY_CLUSTER_WORKER_REPLICAS_MAX_DEFAULT
            )
        )

    @classmethod
    def ray_cluster_worker_min_replicas(cls) -> int:
        """Get Ray cluster worker minimum replicas."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_MIN_REPLICAS, RAY_CLUSTER_WORKER_MIN_REPLICAS_DEFAULT
            )
        )

    @classmethod
    def ray_cluster_worker_min_replicas_max(cls) -> int:
        """Get Ray cluster worker minimum replicas maximum."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX,
                RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX_DEFAULT,
            )
        )

    @classmethod
    def ray_cluster_worker_max_replicas(cls) -> int:
        """Get Ray cluster worker maximum replicas."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_MAX_REPLICAS, RAY_CLUSTER_WORKER_MAX_REPLICAS_DEFAULT
            )
        )

    @classmethod
    def ray_cluster_worker_max_replicas_max(cls) -> int:
        """Get Ray cluster worker maximum replicas maximum."""
        return int(
            os.environ.get(
                RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX,
                RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX_DEFAULT,
            )
        )

    @classmethod
    def ray_cluster_worker_auto_scaling(cls) -> bool:
        """Check if Ray cluster worker auto-scaling is enabled."""
        return bool(os.environ.get(RAY_CLUSTER_WORKER_AUTO_SCALING, False))

    @classmethod
    def ray_cluster_max_readiness_time(cls) -> int:
        """Get Ray cluster maximum readiness time."""
        return int(
            os.environ.get(
                RAY_CLUSTER_MAX_READINESS_TIME, RAY_CLUSTER_MAX_READINESS_TIME_DEFAULT
            )
        )

    @classmethod
    def ray_setup_max_retries(cls) -> int:
        """Get Ray setup maximum retries."""
        return int(os.environ.get(RAY_SETUP_MAX_RETRIES, RAY_SETUP_MAX_RETRIES_DEFAULT))

    @classmethod
    def ray_cluster_no_delete_on_complete(cls) -> bool:
        """Check if Ray cluster should not be deleted on completion."""
        return bool(os.environ.get(RAY_CLUSTER_NO_DELETE_ON_COMPLETE, False))

    @classmethod
    def ray_cluster_cpu_node_selector_label(cls) -> str:
        """Get Ray cluster CPU node selector label."""
        return os.environ.get(
            RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL,
            RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL_DEFAULT,
        )

    @classmethod
    def ray_cluster_gpu_node_selector_label(cls) -> str:
        """Get Ray cluster GPU node selector label."""
        return os.environ.get(
            RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL,
            RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL_DEFAULT,
        )

    # Program Configuration
    @classmethod
    def program_timeout(cls) -> int:
        """Get program timeout in days."""
        return int(os.environ.get(PROGRAM_TIMEOUT, PROGRAM_TIMEOUT_DEFAULT))

    @classmethod
    def gateway_allowlist_config(cls) -> str:
        """Get gateway allowlist configuration path."""
        return str(
            os.environ.get(GATEWAY_ALLOWLIST_CONFIG, GATEWAY_ALLOWLIST_CONFIG_DEFAULT)
        )

    @classmethod
    def gateway_gpu_jobs_config(cls) -> str:
        """Get gateway GPU jobs configuration path."""
        return str(
            os.environ.get(GATEWAY_GPU_JOBS_CONFIG, GATEWAY_GPU_JOBS_CONFIG_DEFAULT)
        )

    @classmethod
    def gateway_dynamic_dependencies(cls) -> str:
        """Get gateway dynamic dependencies path."""
        return str(
            os.environ.get(
                GATEWAY_DYNAMIC_DEPENDENCIES, GATEWAY_DYNAMIC_DEPENDENCIES_DEFAULT
            )
        )

    # IBM Cloud and Qiskit
    @classmethod
    def qiskit_ibm_url(cls) -> str:
        """Get Qiskit IBM URL."""
        return os.environ.get(QISKIT_IBM_URL, QISKIT_IBM_URL_DEFAULT)

    @classmethod
    def iqp_qcon_api_base_url(cls) -> Optional[str]:
        """Get IQP QCON API base URL."""
        return os.environ.get(IQP_QCON_API_BASE_URL, None)

    @classmethod
    def iam_ibm_cloud_base_url(cls) -> Optional[str]:
        """Get IAM IBM Cloud base URL."""
        return os.environ.get(IAM_IBM_CLOUD_BASE_URL, None)

    @classmethod
    def resource_controller_ibm_cloud_base_url(cls) -> Optional[str]:
        """Get Resource Controller IBM Cloud base URL."""
        return os.environ.get(RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL, None)

    @classmethod
    def resource_plans_id_allowed(cls) -> List[str]:
        """Get allowed resource plan IDs."""
        return os.environ.get(RESOURCE_PLANS_ID_ALLOWED, "").split(",")

    # Custom Image
    @classmethod
    def custom_image_package_name(cls) -> str:
        """Get custom image package name."""
        return os.environ.get(
            CUSTOM_IMAGE_PACKAGE_NAME, CUSTOM_IMAGE_PACKAGE_NAME_DEFAULT
        )

    @classmethod
    def custom_image_package_path(cls) -> str:
        """Get custom image package path."""
        return os.environ.get(
            CUSTOM_IMAGE_PACKAGE_PATH, CUSTOM_IMAGE_PACKAGE_PATH_DEFAULT
        )

    # Functions
    @classmethod
    def functions_logs_size_limit(cls) -> str:
        """Get functions logs size limit in MB."""
        return os.environ.get(
            FUNCTIONS_LOGS_SIZE_LIMIT, FUNCTIONS_LOGS_SIZE_LIMIT_DEFAULT
        )

    # OpenTelemetry
    @classmethod
    def otel_exporter_otlp_traces_endpoint(cls) -> str:
        """Get OpenTelemetry exporter OTLP traces endpoint."""
        return os.environ.get(
            OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
            OTEL_EXPORTER_OTLP_TRACES_ENDPOINT_DEFAULT,
        )

    @classmethod
    def otel_exporter_otlp_traces_insecure(cls) -> bool:
        """Check if OpenTelemetry exporter should use insecure connection."""
        return bool(
            int(
                os.environ.get(
                    OTEL_EXPORTER_OTLP_TRACES_INSECURE,
                    OTEL_EXPORTER_OTLP_TRACES_INSECURE_DEFAULT,
                )
            )
        )

    @classmethod
    def otel_enabled(cls) -> bool:
        """Check if OpenTelemetry is enabled."""
        return bool(int(os.environ.get(OTEL_ENABLED, OTEL_ENABLED_DEFAULT)))


# Made with Bob
