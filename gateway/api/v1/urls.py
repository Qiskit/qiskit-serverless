"""
URL Patterns for V1 api application.
"""

from rest_framework import routers
from . import views as v1_views

router = routers.DefaultRouter()
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
    r"runtime_jobs",
    v1_views.RuntimeJobViewSet,
    basename=v1_views.RuntimeJobViewSet.BASE_NAME,
)
router.register(
    r"catalog_entries",
    v1_views.CatalogEntryViewSet,
    basename=v1_views.CatalogEntryViewSet.BASE_NAME,
)

urlpatterns = router.urls
