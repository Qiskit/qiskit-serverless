from .settings_base import *

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
    "api", # for api
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

#JobConfig base configuration
RAY_CLUSTER_WORKER_REPLICAS_MAX = int(
    os.environ.get("RAY_CLUSTER_WORKER_REPLICAS_MAX", "5")
)
RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX = int(
    os.environ.get("RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX", "2")
)

RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX = int(
    os.environ.get("RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX", "10")
)

# qiskit runtime
QISKIT_IBM_CHANNEL = os.environ.get("QISKIT_IBM_CHANNEL", "ibm_quantum")
QISKIT_IBM_URL = os.environ.get(
    "QISKIT_IBM_URL", "https://auth.quantum-computing.ibm.com/api"
)

# quantum api
IQP_QCON_API_BASE_URL = os.environ.get("IQP_QCON_API_BASE_URL", None)

# Providers setup
PROVIDERS_CONFIGURATION = os.environ.get("PROVIDERS_CONFIGURATION", "{}")

# Function permissions
FUNCTIONS_PERMISSIONS = os.environ.get(
    "FUNCTIONS_PERMISSIONS",
    "{}",
)
