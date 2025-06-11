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
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
import probes.views
import version.views

handler500 = "rest_framework.exceptions.server_error"

schema = get_schema_view(  # pylint: disable=invalid-name
    openapi.Info(
        title="Gateway API",
        default_version="v1",
        description="List of available API endpoint for gateway.",
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
    # Patterns to be included in the Swagger documentation
    patterns=[
        re_path(r"^api/v1/", include(("api.v1.urls", "api"), namespace="v1")),
        # Add other included patterns if necessary
    ],
)

urlpatterns = [
    path("readiness/", probes.views.readiness, name="readiness"),
    path("liveness/", probes.views.liveness, name="liveness"),
    path("version/", version.views.version, name="version"),
    path("backoffice/", admin.site.urls),
    re_path(r"^api/v1/", include(("api.v1.urls", "api"), namespace="v1")),
]

urlpatterns += [
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    re_path(
        r"^swagger/$",
        schema.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    re_path(r"^redoc/$", schema.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]
if settings.DEBUG:
    urlpatterns += [path("", include("django_prometheus.urls"))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
