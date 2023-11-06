"""gateway URL Configuration.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import TemplateView
from rest_framework import routers
from .signals import save_job

from api.views import KeycloakLogin, KeycloakUsersView
import probes.views

router = routers.DefaultRouter()


urlpatterns = [
    path("dj-rest-auth/", include("dj_rest_auth.urls")),
    path("dj-rest-auth/keycloak/", KeycloakLogin.as_view(), name="keycloak_login"),
    path("dj-rest-auth/keycloak/login/", KeycloakUsersView.as_view()),
    path("accounts/", include("allauth.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("admin/", admin.site.urls),
    path("readiness/", probes.views.readiness, name="readiness"),
    path("liveness/", probes.views.liveness, name="liveness"),
    path("", include("django_prometheus.urls")),
    re_path(r"^api/v1/", include(("api.v1.urls", "api"), namespace="v1")),
    path(
        "DomainVerification.html",
        TemplateView.as_view(template_name="DomainVerification.html"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
