"""FunctionAccessClient."""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from api.domain.exceptions.runtime_api_exception import RuntimeFunctionsException
from core.config_key import ConfigKey
from core.models import Config

logger = logging.getLogger("api.FunctionAccessClient")


class FunctionAccessClient:
    """Client for retrieving accessible functions for a given instance CRN."""

    def get_accessible_functions(self, instance_crn: str) -> FunctionAccessResult:
        """Return all functions accessible to the given instance CRN with their permissions."""
        enabled = Config.get_bool(ConfigKey.RUNTIME_INSTANCES_API_ENABLED)
        base_url = settings.RUNTIME_API_BASE_URL
        if not enabled:
            return FunctionAccessResult(use_legacy_authorization=True, message="RUNTIME_INSTANCES_API_ENABLED is False")

        if not instance_crn:
            raise RuntimeFunctionsException("Missing instance_crn")

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
        except requests.RequestException as exc:
            logger.exception("FunctionAccessClient: connection error for CRN %s", instance_crn)
            raise RuntimeFunctionsException("Error connecting to Runtime API")

        if response.status_code == 204:
            # We agreed with Runtime that 204 response means there is no functions configured
            # for this instance, so we should fallback to Django
            return FunctionAccessResult(
                use_legacy_authorization=True, message="Instance not configured, migration pending"
            )

        if response.status_code != 200:
            logger.warning(
                "FunctionAccessClient: unexpected status %s for CRN %s",
                response.status_code,
                instance_crn,
            )
            raise RuntimeFunctionsException(f"Unexpected status {response.status_code} for CRN {instance_crn}")

        functions = []
        for entry in response.json().get("functions", []):
            try:
                function_entry = FunctionAccessEntry(
                    provider_name=entry["provider"],
                    function_title=entry["name"],
                    permissions=set(entry.get("permissions", [])),
                    business_model=entry["business_model"],
                )
                functions.append(function_entry)
            except (KeyError, ValueError) as exc:
                # entry with missing field or incorrect business model
                logger.error("FunctionAccessClient: invalid entry %s — %s", entry, exc)

        result = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        cache.set(cache_key, result, timeout=settings.RUNTIME_API_CACHE_TTL)
        return result
