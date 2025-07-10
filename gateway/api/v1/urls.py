"""
URL Patterns for V1 api application.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter
from api.v1 import views as v1_views
from api.v1.route_registry import RouteRegistry

# :: BEGIN -- FORCE IMPORT EVERY VIEW MODULE
import os
import importlib

views_dir = os.path.join(os.path.dirname(__file__), "views")
base_module = "api.v1.views"

for filename in os.listdir(views_dir):
    if filename.endswith(".py") and not filename.startswith("__"):
        module_name = filename[:-3]
        importlib.import_module(f"{base_module}.{module_name}")
        print(f"[IMPORT] api.v1.views.{module_name}")

# :: END --

router = SimpleRouter()
router.register(
    r"programs",
    v1_views.ProgramViewSet,
    basename=v1_views.ProgramViewSet.BASE_NAME,
)
router.register(
    r"jobs",
    v1_views.JobViewSet,
    basename=v1_views.JobViewSet.BASE_NAME,
)
router.register(
    r"files", v1_views.FilesViewSet, basename=v1_views.FilesViewSet.BASE_NAME
)
router.register(
    r"catalog",
    v1_views.CatalogViewSet,
    basename=v1_views.CatalogViewSet.BASE_NAME,
)

urlpatterns = router.urls + RouteRegistry.get()
