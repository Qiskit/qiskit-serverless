"""What the scheduler does with each blocked-account-plan event consumed from Event Streams.

For now it only logs the event. Whatever it does later must be idempotent: the consumer delivers at
least once, and retries an event whose handling raised anything but InvalidEventError.
"""

import logging

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError

logger = logging.getLogger("core.services.blocked_account_events")


def handle_blocked_account_event(payload: dict, key: str | None, region: str) -> None:
    """Handle one blocked-account-plan event.

    Raises:
        InvalidEventError: the event has no account_id, so it can never be handled.
    """
    account_id = payload.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise InvalidEventError(f"event has no account_id (key={key})")

    logger.info(
        "Blocked-account event: region=%s account_id=%s plan_id=%s subscription_id=%s deleted=%s",
        region,
        account_id,
        payload.get("plan_id"),
        payload.get("subscription_id"),
        payload.get("deleted", False),
    )
