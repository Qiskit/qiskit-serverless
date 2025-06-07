"""
URL Patterns for V1 api application.
"""

from rest_framework.routers import SimpleRouter
from api.v1 import views as v1_views

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

urlpatterns = router.urls
