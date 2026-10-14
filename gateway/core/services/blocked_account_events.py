"""What the scheduler does with each blocked-account-plan event consumed from Event Streams: keep
BlockedCloudResource a mirror of the blocked set billing-service publishes.

Upstream publishes state, not increments: a periodic job recomputes the blocked set and emits the diff,
an event with deleted absent or false for a resource that became blocked and deleted true for one that
recovered. So an event upserts or deletes its resource's row by (account, plan, subscription), whichever
topic it comes from, and applying it twice is a no-op. That idempotency is also what the consumer needs: it
delivers at least once, and retries an event whose handling raised anything but InvalidEventError.

Kafka tombstones (a null value) never reach this handler: recovery is always a deleted=true event.
"""

import logging

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource

logger = logging.getLogger("core.services.blocked_account_events")


class BlockedAccountEventsService:
    """Keeps BlockedCloudResource a mirror of the blocked set, one event at a time."""

    # BlockedCloudResource column -> event field
    ACCOUNT_PLAN_SUBSCRIPTION_FIELDS = {"account": "account_id", "plan": "plan_id", "subscription": "subscription_id"}

    def handle(self, payload: dict, key: str | None, region: str) -> None:
        """Block or unblock the event's resource.

        Raises:
            InvalidEventError: the event can never be handled, see _parse_event.
        """
        account_plan_subscription = self._parse_event(payload, key)
        deleted = account_plan_subscription.pop("deleted")

        if deleted:
            removed, _ = BlockedCloudResource.objects.filter(**account_plan_subscription).delete()
            logger.info(
                "Unblocked: region=%s account=%s plan=%s subscription=%s removed=%s",
                region,
                account_plan_subscription["account"],
                account_plan_subscription["plan"],
                account_plan_subscription["subscription"],
                bool(removed),
            )
            return

        _, created = BlockedCloudResource.objects.get_or_create(**account_plan_subscription)
        logger.info(
            "Blocked: region=%s account=%s plan=%s subscription=%s created=%s",
            region,
            account_plan_subscription["account"],
            account_plan_subscription["plan"],
            account_plan_subscription["subscription"],
            created,
        )

    @classmethod
    def _parse_event(cls, payload: dict, key: str | None) -> dict:
        """The event's account, plan, subscription and deleted.

        Raises:
            InvalidEventError: a resource field is missing or empty, not a string or too long to store,
                or deleted is not a boolean.
        """
        event: dict = {}
        missing: list[str] = []
        for column, event_field in cls.ACCOUNT_PLAN_SUBSCRIPTION_FIELDS.items():
            value = payload.get(event_field)
            if value is None or value == "":
                missing.append(event_field)
                continue
            if not isinstance(value, str):
                raise InvalidEventError(f"{event_field} is a {type(value).__name__}, not a string (key={key})")
            max_length = BlockedCloudResource._meta.get_field(column).max_length
            if len(value) > max_length:
                raise InvalidEventError(f"{event_field} is longer than {max_length} characters (key={key})")
            event[column] = value

        if missing:
            raise InvalidEventError(f"event is missing {', '.join(missing)} (key={key})")

        deleted = payload.get("deleted")
        if deleted is not None and not isinstance(deleted, bool):
            raise InvalidEventError(f"deleted is a {type(deleted).__name__}, not a boolean (key={key})")
        event["deleted"] = bool(deleted)
        return event
