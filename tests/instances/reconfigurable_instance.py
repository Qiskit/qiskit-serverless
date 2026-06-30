# pylint: disable=line-too-long
"""The single reconfigurable service instance the acceptance suite drives through NTC.

``NtcAdminClient`` is a generic HTTP client: it knows how to write an account plan and an instance,
but nothing about THIS suite. ``ReconfigurableInstance`` adds the two suite-specific facts the raw
client lacks:

  - the CRN of the instance under test, and
  - the account-plan "superset" that must be in place before any instance write.

Why the superset matters: the broker rejects an instance grant that exceeds the account plan, and the
account->instance sync only ever NARROWS (it never re-adds). So the normal way to put the instance
into a level is "widen the account to the superset, then PATCH the instance" -- which is exactly what
``set_entitlements`` does. The low-level passthroughs (``set_account_entitlements`` / ``patch_instance``)
skip the widening on purpose and exist only for the propagation tests, which need to drive the account
and instance independently (narrow the account below the superset, or PATCH an instance grant that the
account does not allow so the broker rejection can be asserted).
"""

import logging

logger = logging.getLogger("instances.reconfigurable_instance")


class ReconfigurableInstance:
    """One service instance plus its account plan, reconfigured per test through NTC."""

    def __init__(self, ntc, crn, superset_functions, superset_custom):
        self.ntc = ntc
        self.crn = crn
        self.superset_functions = superset_functions
        self.superset_custom = superset_custom

    def widen_account_to_superset(self):
        """Set the account plan to the superset so any instance grant is accepted by the broker.

        The broker rejects an instance PATCH that asks for more than the account currently grants, so
        the account must hold a superset of every level before the instance is reconfigured.
        """
        logger.info(
            "widen account to superset: functions=%d custom=%d",
            len(self.superset_functions),
            len(self.superset_custom),
        )
        self.ntc.set_account_entitlements(self.superset_functions, self.superset_custom)

    def set_entitlements(self, functions, custom_permissions):
        """Put the instance into the given level (the normal path used by every test).

        Widens the account to the superset first (so the broker accepts the write), then PATCHes the
        instance. The instance PATCH carries an advancing timestamp, so the Runtime API re-syncs at
        once and the new state is readable immediately, with no sleep or polling.
        """
        logger.info(
            "set instance entitlements: crn=%s functions=%d custom=%s",
            self.crn,
            len(functions),
            list(custom_permissions) if custom_permissions else "<clear>",
        )
        self.widen_account_to_superset()
        self.ntc.set_instance_entitlements(self.crn, functions, custom_permissions)

    # --- low-level passthroughs (no superset widening) used only by the propagation tests ----------

    def set_account_entitlements(self, functions, custom_permissions):
        """Write the account plan directly, WITHOUT widening to the superset.

        Used by the propagation tests to deliberately narrow the account below the superset and
        observe the account->instance narrow-sync.
        """
        logger.info("set account entitlements (raw): functions=%d", len(functions))
        self.ntc.set_account_entitlements(functions, custom_permissions)

    def patch_instance(self, functions, custom_permissions):
        """PATCH the instance directly, WITHOUT widening the account first.

        Used by the propagation test that asserts the broker rejects an instance grant exceeding the
        current account plan.
        """
        logger.info("patch instance (raw): crn=%s functions=%d", self.crn, len(functions))
        self.ntc.set_instance_entitlements(self.crn, functions, custom_permissions)
