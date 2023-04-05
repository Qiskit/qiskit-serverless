"""main URL Configuration

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
from django.urls import include, path, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

schema = get_schema_view(  # pylint: disable=invalid-name
    openapi.Info(
        title="Program repository API",
        default_version="v1",
        description="List of available API endpoint for Program repository.",
    ),
    public=False,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r"^api/v1/", include(("api.v1.urls", "api"), namespace="v1")),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("", include("django_prometheus.urls")),
    # docs
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
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
