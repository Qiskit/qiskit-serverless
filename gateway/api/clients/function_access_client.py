"""FunctionAccessClient."""

import logging
import os

import requests
from django.conf import settings

from core.config_key import ConfigKey
from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Config

logger = logging.getLogger("api.FunctionAccessClient")


class FunctionAccessClient:
    """Client for retrieving accessible functions for a given instance CRN."""

    def get_accessible_functions(self, instance_crn: str) -> FunctionAccessResult:
        """Return all functions accessible to the given instance CRN with their permissions."""
        # Env var takes precedence (set by docker-compose/k8s for test deployments).
        # Falls back to DB config so ops can toggle at runtime without a redeploy.
        env_override = os.environ.get("RUNTIME_INSTANCES_API_ENABLED")
        if env_override is not None:
            enabled = env_override == "1"
        else:
            enabled = Config.get_bool(ConfigKey.RUNTIME_INSTANCES_API_ENABLED)
        if not enabled:
            return FunctionAccessResult(has_response=False)

        base_url = settings.RUNTIME_INSTANCES_API_BASE_URL
        if not base_url:
            return FunctionAccessResult(has_response=False)

        try:
            response = requests.get(
                f"{base_url}/instances/functions",
                headers={"Service-CRN": instance_crn},
                timeout=5,
            )
        except requests.RequestException:
            logger.exception("FunctionAccessClient: connection error for CRN %s", instance_crn)
            return FunctionAccessResult(has_response=False)

        if response.status_code != 200:
            logger.warning(
                "FunctionAccessClient: unexpected status %s for CRN %s",
                response.status_code,
                instance_crn,
            )
            return FunctionAccessResult(has_response=False)

        functions = []
        for f in response.json().get("functions", []):
            try:
                functions.append(
                    FunctionAccessEntry(
                        provider_name=f["provider"],
                        function_title=f["name"],
                        permissions=set(f.get("permissions", [])),
                        business_model=f["business_model"].upper(),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.error("FunctionAccessClient: invalid entry %s — %s", f, exc)

        return FunctionAccessResult(has_response=True, functions=functions)
