"""What the scheduler does with each blocked-account-plan event consumed from Event Streams: keep
BlockedCloudResource a mirror of the blocked set billing-service publishes.

Upstream publishes state, not increments: a periodic job recomputes the blocked set and emits the diff,
an event with deleted absent or false for a resource that became blocked and deleted true for one that
recovered. So an event upserts or deletes its resource's row by (account, plan, subscription, source),
and applying it twice is a no-op. That idempotency is also what the consumer needs: it delivers at least
once, and retries an event whose handling raised anything but InvalidEventError.

Kafka tombstones (a null value) never reach this handler: recovery is always a deleted=true event.
"""

import logging

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource

logger = logging.getLogger("core.services.blocked_account_events")

# BlockedCloudResource column -> event field
_SCOPE_FIELDS = {"account": "account_id", "plan": "plan_id", "subscription": "subscription_id"}


def handle_blocked_account_event(payload: dict, key: str | None, region: str, topic: str) -> None:
    """Block or unblock the event's resource.

    Raises:
        InvalidEventError: the event can never be handled: it comes from an unknown topic, has no
            scope at all, or has a field of the wrong type or too long to store.
    """
    source = _source(topic)
    scope = _scope(payload, key)
    deleted = payload.get("deleted")
    if deleted is not None and not isinstance(deleted, bool):
        raise InvalidEventError(f"deleted is a {type(deleted).__name__}, not a boolean (key={key})")

    if deleted:
        removed, _ = BlockedCloudResource.objects.filter(**scope, source=source).delete()
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

    _, created = BlockedCloudResource.objects.get_or_create(**scope, source=source)
    logger.info(
        "Blocked: region=%s source=%s account=%s plan=%s subscription=%s created=%s",
        region,
        source,
        scope["account"],
        scope["plan"],
        scope["subscription"],
        created,
    )


def _source(topic: str) -> str:
    """The source of the topic, whatever environment prefixes it, or raise InvalidEventError."""
    for source in BlockedCloudResource.Source:
        if topic.endswith(f".{source}"):
            return source
    raise InvalidEventError(f"topic {topic} is not a blocked-account-plan topic")


def _scope(payload: dict, key: str | None) -> dict[str, str | None]:
    """The event's {account, plan, subscription}, an empty string read as no value, or raise
    InvalidEventError."""
    scope: dict[str, str | None] = {}
    for column, event_field in _SCOPE_FIELDS.items():
        value = payload.get(event_field)
        if value is not None and not isinstance(value, str):
            raise InvalidEventError(f"{event_field} is a {type(value).__name__}, not a string (key={key})")
        max_length = BlockedCloudResource._meta.get_field(column).max_length
        if value is not None and len(value) > max_length:
            raise InvalidEventError(f"{event_field} is longer than {max_length} characters (key={key})")
        # Stored as NULL, so "" and a missing field are the same scope
        scope[column] = value or None

    if not any(scope.values()):
        raise InvalidEventError(f"event has no account_id, plan_id nor subscription_id (key={key})")
    return scope
