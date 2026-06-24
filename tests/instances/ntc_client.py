# pylint: disable=line-too-long
"""Client for configuring NTC accounts and service instances in acceptance tests.

This is a Python port of the bash workflow used to seed the permission tests. It talks to
two NTC hosts with a single bearer token:

  - the account admin API (``quantum.test.cloud.ibm.com``) for account plan entitlements, and
  - the resource-controller (``resource-controller.test.cloud.ibm.com``) for instance entitlements.

All write methods use read-modify-write: they fetch the current document, replace only the
``functions`` / ``custom_functions`` keys, and send the rest back untouched, so existing fields
(plan_id, usage_*, backends, ...) are preserved.

NOTE: the exact request/response payload shapes are derived from the original bash script and the
NTC source. They must be validated against staging; adjust here if NTC's contract differs.
"""

import urllib.parse

import requests


class NtcApiError(Exception):
    """Raised when an NTC endpoint returns a non-2xx response (or a plan is missing)."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _check(response):
    """Raise NtcApiError if the response is not 2xx, otherwise return it."""
    if not 200 <= response.status_code < 300:
        raise NtcApiError(
            f"NTC request to {response.url} failed with HTTP {response.status_code}",
            status=response.status_code,
            body=response.text,
        )
    return response


class NtcAdminClient:
    """Configures account plans and instance entitlements in NTC.

    A single bearer token authenticates against both the account admin API and the
    resource-controller. ``subscription_name`` selects which account plan to mutate.
    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        account_id,
        token,
        admin_base="https://quantum.test.cloud.ibm.com",
        rc_base="https://resource-controller.test.cloud.ibm.com",
        subscription_name="flex",
        timeout=30,
    ):
        self.account_id = account_id
        self.token = token
        self.admin_base = admin_base.rstrip("/")
        self.rc_base = rc_base.rstrip("/")
        self.subscription_name = subscription_name
        self.timeout = timeout

    # --- account (account plans = maximum limit) ---------------------------------------------

    def _account_url(self):
        return f"{self.admin_base}/api/v1/accounts/{self.account_id}"

    def _account_headers(self):
        # The bash script uses a lowercase "bearer" scheme for the account admin API.
        return {"Authorization": f"bearer {self.token}", "Content-Type": "application/json"}

    def get_account(self):
        """Return the account configuration as parsed JSON."""
        response = _check(requests.get(self._account_url(), headers=self._account_headers(), timeout=self.timeout))
        return response.json()

    def set_account_entitlements(self, functions, custom_permissions):
        """Replace the ``functions`` and ``custom_functions`` of the configured plan.

        Read-modify-write: fetch the account, locate the plan whose ``subscription_name`` matches
        ``self.subscription_name`` (never create it), mutate only that plan, and PUT the whole
        document back. Raises NtcApiError if the plan is not present.
        """
        account = self.get_account()
        plans = account.get("plans") or []
        target = None
        for plan in plans:
            if plan.get("subscription_name") == self.subscription_name:
                target = plan
                break
        if target is None:
            raise NtcApiError(f"plan '{self.subscription_name}' not found in account")

        target["functions"] = functions
        if custom_permissions is None:
            target["custom_functions"] = {"permissions": []}
        else:
            target["custom_functions"] = {"permissions": list(custom_permissions)}

        body = {
            "account_id": account.get("account_id") or f"a/{self.account_id}",
            "plans": plans,
        }
        _check(
            requests.put(
                self._account_url(),
                headers=self._account_headers(),
                json=body,
                timeout=self.timeout,
            )
        )

    # --- instance (entitlements) -------------------------------------------------------------

    def _instance_url(self, crn):
        encoded = urllib.parse.quote(crn, safe="")
        return f"{self.rc_base}/v2/resource_instances/{encoded}"

    def _instance_headers(self):
        # The resource-controller uses the capitalized "Bearer" scheme.
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def get_instance(self, crn):
        """Return the service instance document as parsed JSON."""
        response = _check(requests.get(self._instance_url(crn), headers=self._instance_headers(), timeout=self.timeout))
        return response.json()

    def set_instance_entitlements(self, crn, functions, custom_permissions):
        """Replace the instance ``functions`` (and optionally ``custom_functions``).

        Read-modify-write over ``parameters``: other parameters (backends, usage, ...) are kept.
        When ``custom_permissions`` is None, the instance ``custom_functions`` is left untouched.
        """
        instance = self.get_instance(crn)
        params = instance.get("parameters") or {}
        params["functions"] = functions
        if custom_permissions is not None:
            params["custom_functions"] = {"permissions": list(custom_permissions)}
        _check(
            requests.patch(
                self._instance_url(crn),
                headers=self._instance_headers(),
                json={"parameters": params},
                timeout=self.timeout,
            )
        )
