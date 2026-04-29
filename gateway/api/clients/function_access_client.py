"""FunctionAccessClient."""

import logging

import requests
from django.conf import settings

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
        if not enabled:
            return FunctionAccessResult(has_response=False, message="Feature flag is disabled")

        base_url = settings.RUNTIME_INSTANCES_API_BASE_URL
        if not base_url:
            return FunctionAccessResult(has_response=False, message="Url is not defined")

        try:
            response = requests.get(
                f"{base_url}/instances/functions",
                headers={"Service-CRN": instance_crn},
                timeout=5,
            )
        except requests.RequestException as ex:
            logger.exception("FunctionAccessClient: connection error for CRN %s", instance_crn)
            return FunctionAccessResult(has_response=False, message=f"Connection error f{str(ex)}")

        if response.status_code != 200:
            logger.warning(
                "FunctionAccessClient: unexpected status %s for CRN %s",
                response.status_code,
                instance_crn,
            )
            return FunctionAccessResult(has_response=False, message=f"Unexpected status {response.status_code}")

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
                return FunctionAccessResult(has_response=False, message="Json error")

        return FunctionAccessResult(has_response=True, functions=functions, message="Success")
