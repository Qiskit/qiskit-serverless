"""
URL Patterns for V1 api application.
"""

from rest_framework import routers
from . import views as v1_views

router = routers.DefaultRouter()
router.register(
    r"nested-programs",
    v1_views.QuantumFunctionViewSet,
    basename=v1_views.QuantumFunctionViewSet.BASE_NAME,
)
router.register(
    r"jobs",
    v1_views.JobViewSet,
    basename=v1_views.JobViewSet.BASE_NAME,
)

urlpatterns = router.urls
