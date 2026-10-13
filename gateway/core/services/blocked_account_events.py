"""What the scheduler does with each blocked-account-plan event consumed from Event Streams.

For now it only logs the event. Whatever it does later must be idempotent: the consumer delivers at
least once, and retries an event whose handling raised anything but InvalidEventError.
"""

import logging

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError

logger = logging.getLogger("core.services.blocked_account_events")


REQUIRED_FIELDS = ("account_id", "plan_id", "subscription_id")


def handle_blocked_account_event(payload: dict, key: str | None, region: str) -> None:
    """Handle one blocked-account-plan event.

    Raises:
        InvalidEventError: one of REQUIRED_FIELDS is missing or not a non-empty string, so the event
            can never be handled.
    """
    missing = [name for name in REQUIRED_FIELDS if not isinstance(payload.get(name), str) or not payload[name]]
    if missing:
        raise InvalidEventError(f"event is missing {', '.join(missing)} (key={key})")

    logger.info(
        "Blocked-account event: region=%s account_id=%s plan_id=%s subscription_id=%s deleted=%s",
        region,
        payload["account_id"],
        payload["plan_id"],
        payload["subscription_id"],
        payload.get("deleted", False),
    )
