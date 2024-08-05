"""
Django settings for scheduler application.
"""

from .settings_api import *  # pylint: disable=wildcard-import, unused-wildcard-import

# Application definition
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_prometheus",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "allauth",
    "allauth.socialaccount",
    "api",  # scheduler is in the api right now
    "psycopg2",
    "drf_yasg",
]

MIDDLEWARE = [
    "csp.middleware.CSPMiddleware",
    "allow_cidr.middleware.AllowCIDRMiddleware",
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

# resources limitations
LIMITS_JOBS_PER_USER = int(os.environ.get("LIMITS_JOBS_PER_USER", "2"))
LIMITS_MAX_CLUSTERS = int(os.environ.get("LIMITS_MAX_CLUSTERS", "6"))
LIMITS_CPU_PER_TASK = int(os.environ.get("LIMITS_CPU_PER_TASK", "4"))
LIMITS_MEMORY_PER_TASK = int(os.environ.get("LIMITS_MEMORY_PER_TASK", "8"))

# ray cluster management
RAY_KUBERAY_NAMESPACE = os.environ.get("RAY_KUBERAY_NAMESPACE", "qiskit-serverless")
RAY_CLUSTER_MODE = {
    "local": int(os.environ.get("RAY_CLUSTER_MODE_LOCAL", 0)),
    "ray_local_host": os.environ.get(
        "RAY_CLUSTER_MODE_LOCAL_HOST", "http://localhost:8265"
    ),
}
RAY_NODE_IMAGE = os.environ.get(
    "RAY_NODE_IMAGE", "icr.io/quantum-public/qiskit-serverless/ray-node:0.14.2"
)
RAY_CLUSTER_WORKER_REPLICAS = int(os.environ.get("RAY_CLUSTER_WORKER_REPLICAS", "1"))
RAY_CLUSTER_WORKER_MIN_REPLICAS = int(
    os.environ.get("RAY_CLUSTER_WORKER_MIN_REPLICAS", "1")
)
RAY_CLUSTER_WORKER_MAX_REPLICAS = int(
    os.environ.get("RAY_CLUSTER_WORKER_MAX_REPLICAS", "4")
)
RAY_CLUSTER_WORKER_AUTO_SCALING = bool(
    os.environ.get("RAY_CLUSTER_WORKER_AUTO_SCALING", False)
)
RAY_CLUSTER_MAX_READINESS_TIME = int(
    os.environ.get("RAY_CLUSTER_MAX_READINESS_TIME", "120")
)
RAY_SETUP_MAX_RETRIES = int(os.environ.get("RAY_SETUP_MAX_RETRIES", 30))
RAY_CLUSTER_NO_DELETE_ON_COMPLETE = bool(
    os.environ.get("RAY_CLUSTER_NO_DELETE_ON_COMPLETE", False)
)

# Scheduler configuration
PROGRAM_TIMEOUT = int(os.environ.get("PROGRAM_TIMEOUT", "14"))

# qiskit runtime
QISKIT_IBM_CHANNEL = os.environ.get("QISKIT_IBM_CHANNEL", "ibm_quantum")
QISKIT_IBM_URL = os.environ.get(
    "QISKIT_IBM_URL", "https://auth.quantum-computing.ibm.com/api"
)

# Custom image for programs settings
CUSTOM_IMAGE_PACKAGE_NAME = os.environ.get("CUSTOM_IMAGE_PACKAGE_NAME", "runner")
CUSTOM_IMAGE_PACKAGE_PATH = os.environ.get("CUSTOM_IMAGE_PACKAGE_PATH", "/runner")

# Providers setup
PROVIDERS_CONFIGURATION = os.environ.get("PROVIDERS_CONFIGURATION", "{}")

# Function permissions
FUNCTIONS_PERMISSIONS = os.environ.get(
    "FUNCTIONS_PERMISSIONS",
    "{}",
)
