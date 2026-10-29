"""What the scheduler does with each blocked-account-plan event consumed from Event Streams: keep
BlockedCloudResource a mirror of the blocked set billing-service publishes.

Upstream publishes state, not increments: a periodic job recomputes the blocked set and emits the diff,
an event with deleted absent or false for a resource that became blocked and deleted true for one that
recovered. Each topic reports one limit, so the topic gives the row its reason, and the row also keeps
the region the event came from. An event upserts or deletes its resource's row by (account, plan,
subscription, reason, region): an unblock never lifts a block another limit or region still holds, and
applying an event twice is a no-op. That idempotency is also what the consumer needs: it
delivers at least once, and retries an event whose handling raised anything but InvalidEventError.

Kafka tombstones (a null value) never reach this handler: recovery is always a deleted=true event.
"""

import logging

from core.domain.crn import ACCOUNT_PREFIX
from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource

logger = logging.getLogger("core.services.blocked_account_events")


class BlockedAccountEventsService:
    """Keeps BlockedCloudResource a mirror of the blocked set, one event at a time."""

    # BlockedCloudResource column -> event field
    ACCOUNT_PLAN_SUBSCRIPTION_FIELDS = {"account": "account_id", "plan": "plan_id", "subscription": "subscription_id"}

    def __init__(self, topic_reasons: dict[str, str]):
        """topic_reasons maps each topic consumed to the reason its blocks are stored under."""
        self.topic_reasons = topic_reasons

    def handle(self, payload: dict, key: str | None, region: str, topic: str) -> None:
        """Block or unblock the event's resource, for the reason its topic reports, in its region.

        Raises:
            InvalidEventError: the event can never be handled, see _parse_event, or its topic has no reason.
        """
        reason = self.topic_reasons.get(topic)
        if reason is None:
            raise InvalidEventError(f"topic {topic} has no blocking reason (key={key})")
        account_plan_subscription = self._parse_event(payload, key)
        deleted = account_plan_subscription.pop("deleted")
        row = {**account_plan_subscription, "reason": reason, "region": region}

        if deleted:
            removed, _ = BlockedCloudResource.objects.filter(**row).delete()
            logger.info(
                "Unblocked: region=%s reason=%s account=%s plan=%s subscription=%s removed=%s",
                region,
                reason,
                row["account"],
                row["plan"],
                row["subscription"],
                bool(removed),
            )
            return

        _, created = BlockedCloudResource.objects.get_or_create(**row)
        logger.info(
            "Blocked: region=%s reason=%s account=%s plan=%s subscription=%s created=%s",
            region,
            reason,
            row["account"],
            row["plan"],
            row["subscription"],
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
            if column == "account" and isinstance(value, str):
                # Jobs store the bare account id from the IAM token, so the row has to match it
                value = value.removeprefix(ACCOUNT_PREFIX)
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
