"""Events: short facts about what happened in the chat, published to Kafka for others to use.

The chat publishes and moves on. It does not know who reads the events, and it does not wait
for them: a worker that is slow or stopped never slows down or breaks a reply.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from confluent_kafka import KafkaError, Message, Producer

from agent.config import Settings
from agent.logs import request_id
from agent.metrics import EVENTS

log = logging.getLogger(__name__)
TOPIC = "chat-events"


def event(kind: str, conversation_id: str, **fields: Any) -> dict[str, Any]:
    """One event. event_id is unique, so a consumer can tell a repeat from a new event."""
    return {
        "event_id": uuid.uuid4().hex,
        "type": kind,
        "conversation_id": conversation_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        **fields,
    }


class Events(Protocol):
    """Anything that can publish an event: Kafka in the service, a list in the tests."""

    def publish(self, event: dict[str, Any]) -> None: ...


class KafkaEvents:
    """Publishes events to a Kafka topic. Never blocks the chat: produce() only queues."""

    def __init__(self, servers: str, topic: str = TOPIC) -> None:
        self.topic = topic
        self.producer = Producer(
            {
                "bootstrap.servers": servers,
                "acks": "all",  # the broker confirms only after the event is safely stored
                "enable.idempotence": True,  # a retried send is stored once, not twice
                "message.timeout.ms": 30000,  # give up on an event after 30 s
                # librdkafka's own messages, through Python logging: JSON like ours.
                "logger": logging.getLogger("kafka"),
            }
        )

    def publish(self, event: dict[str, Any]) -> None:
        # Metadata travels in headers, as in HTTP: the request that caused this event.
        current = request_id.get()
        headers: dict[str, str | bytes | None] = {"request_id": current} if current else {}
        # The key decides the partition: all events of one conversation stay in order.
        self.producer.produce(
            self.topic,
            key=event["conversation_id"],
            value=json.dumps(event).encode("utf-8"),
            headers=headers,
            on_delivery=self._delivered,
        )
        EVENTS.labels("queued").inc()
        self.producer.poll(0)  # run the callbacks of earlier sends; do not wait

    def _delivered(self, error: KafkaError | None, message: Message) -> None:
        if error is not None:
            EVENTS.labels("lost").inc()  # the dual-write gap, made visible
            log.error("event lost: %s (%s)", error, message.value())
        else:
            EVENTS.labels("delivered").inc()

    def close(self, timeout: float = 5.0) -> None:
        """Send what is still queued, waiting at most `timeout` seconds."""
        left = self.producer.flush(timeout)
        if left:
            log.error("%d events were never sent", left)


def make_events(settings: Settings) -> KafkaEvents | None:
    """The publisher, or None when no Kafka is set up (KAFKA_BOOTSTRAP_SERVERS unset)."""
    if not settings.kafka_servers:
        return None
    return KafkaEvents(settings.kafka_servers)
