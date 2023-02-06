from rest_framework import routers
from . import views as v1_views

router = routers.DefaultRouter()
router.register(
    r"nested-programs",
    v1_views.NestedProgramViewSet,
    basename=v1_views.NestedProgramViewSet.BASE_NAME,
)

urlpatterns = router.urls
