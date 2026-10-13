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
    SCOPE_FIELDS = {"account": "account_id", "plan": "plan_id", "subscription": "subscription_id"}

    def handle(self, payload: dict, key: str | None, region: str, topic: str) -> None:
        """Block or unblock the event's resource.

        Raises:
            InvalidEventError: the event can never be handled: it comes from an unknown topic, misses
                a scope field, or has a field of the wrong type or too long to store.
        """
        source = self._source(topic)
        scope = self._scope(payload, key)
        deleted = payload.get("deleted")
        if deleted is not None and not isinstance(deleted, bool):
            raise InvalidEventError(f"deleted is a {type(deleted).__name__}, not a boolean (key={key})")

        if deleted:
            removed, _ = BlockedCloudResource.objects.filter(**scope).delete()
            logger.info(
                "Unblocked: region=%s source=%s account=%s plan=%s subscription=%s removed=%s",
                region,
                source,
                scope["account"],
                scope["plan"],
                scope["subscription"],
                bool(removed),
            )
            return

        # The row keeps the source of the first block: a later one from the other topic changes nothing
        _, created = BlockedCloudResource.objects.get_or_create(**scope, defaults={"source": source})
        logger.info(
            "Blocked: region=%s source=%s account=%s plan=%s subscription=%s created=%s",
            region,
            source,
            scope["account"],
            scope["plan"],
            scope["subscription"],
            created,
        )

    @staticmethod
    def _source(topic: str) -> str:
        """The source of the topic, whatever environment prefixes it, or raise InvalidEventError."""
        for source in BlockedCloudResource.Source:
            if topic.endswith(f".{source}"):
                return source
        raise InvalidEventError(f"topic {topic} is not a blocked-account-plan topic")

    @classmethod
    def _scope(cls, payload: dict, key: str | None) -> dict[str, str]:
        """The event's {account, plan, subscription}, or raise InvalidEventError if one is missing or
        empty, not a string, or too long to store."""
        scope: dict[str, str] = {}
        missing: list[str] = []
        for column, event_field in cls.SCOPE_FIELDS.items():
            value = payload.get(event_field)
            if value is None or value == "":
                missing.append(event_field)
                continue
            if not isinstance(value, str):
                raise InvalidEventError(f"{event_field} is a {type(value).__name__}, not a string (key={key})")
            max_length = BlockedCloudResource._meta.get_field(column).max_length
            if len(value) > max_length:
                raise InvalidEventError(f"{event_field} is longer than {max_length} characters (key={key})")
            scope[column] = value

        if missing:
            raise InvalidEventError(f"event is missing {', '.join(missing)} (key={key})")
        return scope
