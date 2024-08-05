from .settings_api import *

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin", # for admin_panel
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
    "api",
    "admin_panel", # for admin_panel
    "psycopg2",
    "drf_yasg",
]

MIDDLEWARE = [
    "csp.middleware.CSPMiddleware",
    "allow_cidr.middleware.AllowCIDRMiddleware",
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", # for admin_panel, must be after session
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]
