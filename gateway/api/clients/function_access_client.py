"""FunctionAccessClient."""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.config_key import ConfigKey
from core.models import Config

logger = logging.getLogger("api.FunctionAccessClient")


class FunctionAccessClient:
    """Client for retrieving accessible functions for a given instance CRN."""

    def get_accessible_functions(self, instance_crn: str) -> FunctionAccessResult:
        """Return all functions accessible to the given instance CRN with their permissions."""
        enabled = Config.get_bool(ConfigKey.RUNTIME_INSTANCES_API_ENABLED)
        base_url = settings.RUNTIME_API_BASE_URL
        if not enabled or not base_url:
            return FunctionAccessResult(has_response=False)

        cache_key = f"accesible_functions:{instance_crn}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{base_url}/api/v1/functions",
                headers={"Service-CRN": instance_crn},
                timeout=5,
            )
        except requests.RequestException:
            logger.exception("FunctionAccessClient: connection error for CRN %s", instance_crn)
            return FunctionAccessResult(has_response=False)

        if response.status_code == 204:
            # We agreed with Runtime that 204 response means there is no functions configured
            # for this instance, so we should fallback to Django
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

        result = FunctionAccessResult(has_response=True, functions=functions)
        cache.set(cache_key, result, timeout=settings.RUNTIME_API_CACHE_TTL)
        return result
