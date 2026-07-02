# pylint: disable=line-too-long
"""The single service instance the acceptance suite drives through NTC.

``NtcAdminClient`` is a generic HTTP client: it knows how to write an account plan and an instance,
but nothing about THIS suite. ``InstanceClient`` adds the two suite-specific facts the raw client
lacks:

  - the CRN of the instance under test, and
  - the account-plan "superset" that must be in place before any instance write.

Why the superset matters: the broker rejects an instance grant that exceeds the account plan, and the
account->instance sync only ever NARROWS (it never re-adds). So putting the instance into a level is
two writes: first widen the account (``reset_account_with_all_functions``), then PATCH the instance
(``set_entitlements``). These are kept as two SEPARATE methods on purpose, so each test performs the
two API writes explicitly and in order, instead of one method silently doing both.

``set_account_entitlements`` writes the account plan to an arbitrary set (the propagation tests use it
to narrow the account below the superset and observe the account->instance sync).
"""

import logging

logger = logging.getLogger("instances.instance_client")


class InstanceClient:
    """One service instance plus its account plan, reconfigured per test through NTC."""

    def __init__(self, ntc, crn, superset_functions, superset_custom):
        self.ntc = ntc
        self.crn = crn
        self.superset_functions = superset_functions
        self.superset_custom = superset_custom

    def reset_account_with_all_functions(self):
        """Write the account plan to the superset so any instance grant is accepted by the broker.

        The broker rejects an instance PATCH that asks for more than the account currently grants, so
        the account must hold a superset of every level before the instance is reconfigured. Tests call
        this explicitly, right before ``set_entitlements``, so both API writes (account, then instance)
        are visible at the call site.
        """
        logger.info(
            "reset account to all functions: functions=%d custom=%d",
            len(self.superset_functions),
            len(self.superset_custom),
        )
        self.set_account_entitlements(self.superset_functions, self.superset_custom)

    def set_account_entitlements(self, functions, custom_permissions):
        """Write the account plan directly to the given entitlements.

        ``reset_account_with_all_functions`` is the common case (the superset); the propagation tests
        call this directly to narrow the account below the superset and observe the account->instance
        narrow-sync.
        """
        logger.info("set account entitlements: functions=%d", len(functions))
        self.ntc.set_account_entitlements(functions, custom_permissions)

    def set_entitlements(self, functions, custom_permissions):
        """PATCH the instance to the given entitlements (a single API write, no account change).

        The caller must widen the account first (``reset_account_with_all_functions``) whenever the new
        instance grant would otherwise exceed the account plan, so the two writes stay explicit at the
        call site. The instance PATCH carries an advancing timestamp, so the Runtime API re-syncs at
        once and the new state is readable immediately, with no sleep or polling.
        """
        logger.info(
            "set instance entitlements: crn=%s functions=%d custom=%s",
            self.crn,
            len(functions),
            list(custom_permissions) if custom_permissions else "<clear>",
        )
        self.ntc.set_instance_entitlements(self.crn, functions, custom_permissions)
