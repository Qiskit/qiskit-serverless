"""
URL Patterns for V1 api application.
"""

import os
import importlib
import logging

from rest_framework.routers import SimpleRouter
from api.v1 import views as v1_views
from api.v1.route_registry import RouteRegistry


logger = logging.getLogger("gateway.v1.urls")


###
# Force imports of every view module
###
views_dir = os.path.join(os.path.dirname(__file__), "views")
BASE_MODULE = "api.v1.views"


def import_dir(directory: str, base_module: str):
    """Force imports of every view module"""
    for filename in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, filename)):
            import_dir(os.path.join(directory, filename), f"{base_module}.{filename}")
        elif filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            importlib.import_module(f"{base_module}.{module_name}")
            logger.debug("[IMPORT] api.v1.views.%s", module_name)


import_dir(views_dir, BASE_MODULE)

router = SimpleRouter()
router.register(
    r"programs",
    v1_views.ProgramViewSet,
    basename=v1_views.ProgramViewSet.BASE_NAME,
)

urlpatterns = RouteRegistry.get() + router.urls
