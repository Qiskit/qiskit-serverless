"""Centralized configuration for environment variables."""

import os
from typing import List, Optional


class Config:
    """Centralized configuration for environment variables.

    This class provides type-safe access to environment variables with
    consistent default values across the codebase.
    """

    # Version and Debug
    @classmethod
    def version(cls) -> str:
        """Get release version."""
        return os.environ.get("VERSION", "UNKNOWN")

    @classmethod
    def debug(cls) -> bool:
        """Check if debug mode is enabled."""
        return bool(int(os.environ.get("DEBUG", "1")))

    @classmethod
    def log_level(cls) -> str:
        """Get log level based on debug setting."""
        return "DEBUG" if cls.debug() else "INFO"

    # Security
    @classmethod
    def secret_key(cls) -> str:
        """Get Django secret key."""
        return os.environ.get(
            "DJANGO_SECRET_KEY",
            "django-insecure-&)i3b5aue*#-i6k9i-03qm(d!0h&662lbhj12on_*gimn3x8p7",
        )

    @classmethod
    def allowed_hosts(cls) -> List[str]:
        """Get allowed hosts."""
        return os.environ.get("ALLOWED_HOSTS", "*").split(",")

    @classmethod
    def csrf_trusted_origins(cls) -> List[str]:
        """Get CSRF trusted origins."""
        return os.environ.get("CSRF_TRUSTED_ORIGINS", "http://localhost").split(",")

    @classmethod
    def cors_allowed_origin_regexes(cls) -> List[str]:
        """Get CORS allowed origin regexes."""
        patterns = os.environ.get(
            "CORS_ALLOWED_ORIGIN_REGEXES", "http://localhost"
        ).split(",")
        return [rf"{pattern}" for pattern in patterns]

    # Database
    @classmethod
    def database_name(cls) -> str:
        """Get database name."""
        return os.environ.get("DATABASE_NAME", "serverlessdb")

    @classmethod
    def database_user(cls) -> str:
        """Get database user."""
        return os.environ.get("DATABASE_USER", "serverlessuser")

    @classmethod
    def database_password(cls) -> str:
        """Get database password."""
        return os.environ.get("DATABASE_PASSWORD", "serverlesspassword")

    @classmethod
    def database_host(cls) -> str:
        """Get database host."""
        return os.environ.get("DATABASE_HOST", "localhost")

    @classmethod
    def database_port(cls) -> str:
        """Get database port."""
        return os.environ.get("DATABASE_PORT", "5432")

    # Authentication
    @classmethod
    def auth_mechanism(cls) -> str:
        """Get authentication mechanism."""
        return os.environ.get("SETTINGS_AUTH_MECHANISM", "default")

    @classmethod
    def auth_mock_token(cls) -> str:
        """Get mock authentication token."""
        return os.environ.get("SETTINGS_AUTH_MOCK_TOKEN", "awesome_token")

    @classmethod
    def auth_mockprovider_registry(cls) -> Optional[str]:
        """Get mock provider registry."""
        return os.environ.get("SETTINGS_AUTH_MOCKPROVIDER_REGISTRY", None)

    @classmethod
    def quantum_platform_api_base_url(cls) -> Optional[str]:
        """Get Quantum Platform API base URL."""
        return os.environ.get("QUANTUM_PLATFORM_API_BASE_URL", None)

    @classmethod
    def token_auth_verification_field(cls) -> Optional[str]:
        """Get token authentication verification field."""
        return os.environ.get("SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD", None)

    # Site
    @classmethod
    def site_host(cls) -> str:
        """Get site host."""
        return os.environ.get("SITE_HOST", "http://localhost:8000")

    # Resource Limits
    @classmethod
    def limits_jobs_per_user(cls) -> int:
        """Get maximum jobs per user."""
        return int(os.environ.get("LIMITS_JOBS_PER_USER", "2"))

    @classmethod
    def limits_max_clusters(cls) -> int:
        """Get maximum clusters."""
        return int(os.environ.get("LIMITS_MAX_CLUSTERS", "6"))

    @classmethod
    def limits_gpu_clusters(cls) -> int:
        """Get maximum GPU clusters."""
        return int(os.environ.get("LIMITS_MAX_GPU_CLUSTERS", "1"))

    @classmethod
    def limits_cpu_per_task(cls) -> int:
        """Get CPU limit per task."""
        return int(os.environ.get("LIMITS_CPU_PER_TASK", "4"))

    @classmethod
    def limits_gpu_per_task(cls) -> int:
        """Get GPU limit per task."""
        return int(os.environ.get("LIMITS_GPU_PER_TASK", "1"))

    @classmethod
    def limits_memory_per_task(cls) -> int:
        """Get memory limit per task."""
        return int(os.environ.get("LIMITS_MEMORY_PER_TASK", "8"))

    @classmethod
    def maintenance(cls) -> bool:
        """Check if maintenance mode is enabled."""
        return os.environ.get("MAINTENANCE", "false") == "true"

    # Ray Cluster Configuration
    @classmethod
    def ray_kuberay_namespace(cls) -> str:
        """Get Ray KubeRay namespace."""
        return os.environ.get("RAY_KUBERAY_NAMESPACE", "qiskit-serverless")

    @classmethod
    def ray_cluster_mode_local(cls) -> int:
        """Get Ray cluster local mode setting."""
        return int(os.environ.get("RAY_CLUSTER_MODE_LOCAL", "0"))

    @classmethod
    def ray_cluster_mode_local_host(cls) -> str:
        """Get Ray cluster local host."""
        return os.environ.get("RAY_CLUSTER_MODE_LOCAL_HOST", "http://localhost:8265")

    @classmethod
    def ray_node_image(cls) -> str:
        """Get Ray node image."""
        return os.environ.get(
            "RAY_NODE_IMAGE", "icr.io/quantum-public/qiskit-serverless/ray-node:0.27.1"
        )

    @classmethod
    def ray_cluster_worker_replicas(cls) -> int:
        """Get Ray cluster worker replicas."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_REPLICAS", "1"))

    @classmethod
    def ray_cluster_worker_replicas_max(cls) -> int:
        """Get Ray cluster worker replicas maximum."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_REPLICAS_MAX", "5"))

    @classmethod
    def ray_cluster_worker_min_replicas(cls) -> int:
        """Get Ray cluster worker minimum replicas."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_MIN_REPLICAS", "1"))

    @classmethod
    def ray_cluster_worker_min_replicas_max(cls) -> int:
        """Get Ray cluster worker minimum replicas maximum."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX", "2"))

    @classmethod
    def ray_cluster_worker_max_replicas(cls) -> int:
        """Get Ray cluster worker maximum replicas."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_MAX_REPLICAS", "4"))

    @classmethod
    def ray_cluster_worker_max_replicas_max(cls) -> int:
        """Get Ray cluster worker maximum replicas maximum."""
        return int(os.environ.get("RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX", "10"))

    @classmethod
    def ray_cluster_worker_auto_scaling(cls) -> bool:
        """Check if Ray cluster worker auto-scaling is enabled."""
        return bool(os.environ.get("RAY_CLUSTER_WORKER_AUTO_SCALING", False))

    @classmethod
    def ray_cluster_max_readiness_time(cls) -> int:
        """Get Ray cluster maximum readiness time."""
        return int(os.environ.get("RAY_CLUSTER_MAX_READINESS_TIME", "120"))

    @classmethod
    def ray_setup_max_retries(cls) -> int:
        """Get Ray setup maximum retries."""
        return int(os.environ.get("RAY_SETUP_MAX_RETRIES", "30"))

    @classmethod
    def ray_cluster_no_delete_on_complete(cls) -> bool:
        """Check if Ray cluster should not be deleted on completion."""
        return bool(os.environ.get("RAY_CLUSTER_NO_DELETE_ON_COMPLETE", False))

    @classmethod
    def ray_cluster_cpu_node_selector_label(cls) -> str:
        """Get Ray cluster CPU node selector label."""
        return os.environ.get(
            "RAY_CLUSTER_CPU_NODE_SELECTOR_LABEL",
            "ibm-cloud.kubernetes.io/worker-pool-name: default",
        )

    @classmethod
    def ray_cluster_gpu_node_selector_label(cls) -> str:
        """Get Ray cluster GPU node selector label."""
        return os.environ.get(
            "RAY_CLUSTER_GPU_NODE_SELECTOR_LABEL",
            "ibm-cloud.kubernetes.io/worker-pool-name: gpu-workers",
        )

    # Program Configuration
    @classmethod
    def program_timeout(cls) -> int:
        """Get program timeout in days."""
        return int(os.environ.get("PROGRAM_TIMEOUT", "14"))

    @classmethod
    def gateway_allowlist_config(cls) -> str:
        """Get gateway allowlist configuration path."""
        return str(os.environ.get("GATEWAY_ALLOWLIST_CONFIG", "api/v1/allowlist.json"))

    @classmethod
    def gateway_gpu_jobs_config(cls) -> str:
        """Get gateway GPU jobs configuration path."""
        return str(os.environ.get("GATEWAY_GPU_JOBS_CONFIG", "api/v1/gpu-jobs.json"))

    @classmethod
    def gateway_dynamic_dependencies(cls) -> str:
        """Get gateway dynamic dependencies path."""
        return str(
            os.environ.get(
                "GATEWAY_DYNAMIC_DEPENDENCIES", "requirements-dynamic-dependencies.txt"
            )
        )

    # IBM Cloud and Qiskit
    @classmethod
    def qiskit_ibm_url(cls) -> str:
        """Get Qiskit IBM URL."""
        return os.environ.get("QISKIT_IBM_URL", "https://cloud.ibm.com")

    @classmethod
    def iqp_qcon_api_base_url(cls) -> Optional[str]:
        """Get IQP QCON API base URL."""
        return os.environ.get("IQP_QCON_API_BASE_URL", None)

    @classmethod
    def iam_ibm_cloud_base_url(cls) -> Optional[str]:
        """Get IAM IBM Cloud base URL."""
        return os.environ.get("IAM_IBM_CLOUD_BASE_URL", None)

    @classmethod
    def resource_controller_ibm_cloud_base_url(cls) -> Optional[str]:
        """Get Resource Controller IBM Cloud base URL."""
        return os.environ.get("RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL", None)

    @classmethod
    def resource_plans_id_allowed(cls) -> List[str]:
        """Get allowed resource plan IDs."""
        return os.environ.get("RESOURCE_PLANS_ID_ALLOWED", "").split(",")

    # Custom Image
    @classmethod
    def custom_image_package_name(cls) -> str:
        """Get custom image package name."""
        return os.environ.get("CUSTOM_IMAGE_PACKAGE_NAME", "runner")

    @classmethod
    def custom_image_package_path(cls) -> str:
        """Get custom image package path."""
        return os.environ.get("CUSTOM_IMAGE_PACKAGE_PATH", "/runner")

    # Functions
    @classmethod
    def functions_logs_size_limit(cls) -> str:
        """Get functions logs size limit in MB."""
        return os.environ.get("FUNCTIONS_LOGS_SIZE_LIMIT", "50")

    # OpenTelemetry
    @classmethod
    def otel_exporter_otlp_traces_endpoint(cls) -> str:
        """Get OpenTelemetry exporter OTLP traces endpoint."""
        return os.environ.get(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"
        )

    @classmethod
    def otel_exporter_otlp_traces_insecure(cls) -> bool:
        """Check if OpenTelemetry exporter should use insecure connection."""
        return bool(int(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "0")))

    @classmethod
    def otel_enabled(cls) -> bool:
        """Check if OpenTelemetry is enabled."""
        return bool(int(os.environ.get("OTEL_ENABLED", "0")))


# Made with Bob
