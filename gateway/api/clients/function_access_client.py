"""FunctionAccessClient."""

import hashlib
import logging
from urllib.parse import urlparse, urlunparse

import requests
from django.conf import settings
from django.core.cache import cache

from api.domain.exceptions.runtime_api_exception import RuntimeFunctionsException
from core.config_key import ConfigKey
from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Config

logger = logging.getLogger("api.FunctionAccessClient")


class FunctionAccessClient:
    """Client for retrieving accessible functions for a given instance CRN."""

    def _regional_base_url(self, base_url: str, instance_crn: str) -> str:
        """Return the Runtime API base URL for the region encoded in ``instance_crn``.

        The Runtime API is region-scoped: the default region (see
        ``RUNTIME_API_DEFAULT_REGION``) is served by the bare host, while other regions
        are reached via a ``{region}.`` host prefix (e.g. ``eu-de.quantum.cloud.ibm.com``).
        The region is the 6th ``:``-delimited segment of the CRN
        (``crn:v1:bluemix:public:quantum-computing:<region>:...``). A CRN whose region
        cannot be parsed falls back to ``base_url`` unchanged.
        """
        parts = instance_crn.split(":") if instance_crn else []
        region = parts[5] if len(parts) > 6 else None
        if not region or region == settings.RUNTIME_API_DEFAULT_REGION:
            return base_url
        parsed = urlparse(base_url)
        return urlunparse(parsed._replace(netloc=f"{region}.{parsed.netloc}"))

    def _instance_entitlements(self, response_json: dict, instance_crn: str) -> dict:
        """Return the ``instance_entitlements`` element holding what ``instance_crn`` is entitled to.

        An element carries either entitlements or an ``error``. It is raised rather than read as an
        instance entitled to nothing, which would turn "unknown" into a clean deny.
        """
        for element in response_json.get("instance_entitlements") or []:
            if element.get("instance_crn") != instance_crn:
                continue
            error = element.get("error") or {}
            if error:
                logger.warning(
                    "FunctionAccessClient: entitlements error %s for CRN %s: %s",
                    error.get("code"),
                    instance_crn,
                    error.get("message"),
                )
                raise RuntimeFunctionsException(f"Runtime API error {error.get('code')} for CRN {instance_crn}")
            return element

        logger.warning("FunctionAccessClient: no entitlements element for CRN %s", instance_crn)
        raise RuntimeFunctionsException(f"No entitlements for CRN {instance_crn}")

    def get_accessible_functions(self, instance_crn: str, api_key: str) -> FunctionAccessResult:
        """Return all functions accessible to the given instance CRN with their permissions."""
        # The Runtime API trims every CRN it is sent and resolves it by exact match, then echoes its
        # own stored value back, so trimming here keeps the CRN sent, the CRN compared against the
        # response and the cache key one and the same string.
        instance_crn = (instance_crn or "").strip()
        enabled = Config.get_bool(ConfigKey.RUNTIME_INSTANCES_API_ENABLED)
        base_url = self._regional_base_url(settings.RUNTIME_API_BASE_URL, instance_crn)
        if not enabled:
            return FunctionAccessResult(use_legacy_authorization=True, message="RUNTIME_INSTANCES_API_ENABLED is False")

        if not instance_crn:
            raise RuntimeFunctionsException("Missing instance_crn")

        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        cache_key = f"accesible_functions:{instance_crn}:{api_key_hash}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{base_url}/api/v1/entitlements",
                headers={"Service-CRN": instance_crn, "Authorization": f"apikey {api_key}"},
                timeout=5,
            )
        except requests.RequestException as exc:
            logger.exception("FunctionAccessClient: connection error for CRN %s", instance_crn)
            raise RuntimeFunctionsException("Error connecting to Runtime API") from exc

        if response.status_code == 204:
            # We agreed with Runtime that 204 response means there is no functions configured
            # for this instance, so we should fallback to Django
            result = FunctionAccessResult(
                use_legacy_authorization=True, message="Instance not configured, migration pending"
            )
        elif response.status_code != 200:
            logger.warning(
                "FunctionAccessClient: unexpected status %s for CRN %s",
                response.status_code,
                instance_crn,
            )
            raise RuntimeFunctionsException(f"Unexpected status {response.status_code} for CRN {instance_crn}")
        else:
            entitlements = self._instance_entitlements(response.json(), instance_crn)
            functions = []
            for entry in entitlements.get("functions") or []:
                try:
                    function_entry = FunctionAccessEntry(
                        provider_name=entry["provider"],
                        function_title=entry["name"],
                        permissions=set(entry.get("permissions") or []),
                        business_model=entry["business_model"],
                    )
                    functions.append(function_entry)
                except (KeyError, ValueError) as exc:
                    # entry with missing field or incorrect business model
                    logger.error("FunctionAccessClient: invalid entry %s — %s", entry, exc)

            # custom_functions is absent when the instance is granted none, and present but null when
            # a grant was cleared, so coalesce both levels to avoid AttributeError on None.get(...).
            custom_function_permissions = set((entitlements.get("custom_functions") or {}).get("permissions") or [])
            result = FunctionAccessResult(
                use_legacy_authorization=False,
                functions=functions,
                custom_function_permissions=custom_function_permissions,
            )
        cache.set(cache_key, result, timeout=settings.RUNTIME_API_CACHE_TTL)
        return result
