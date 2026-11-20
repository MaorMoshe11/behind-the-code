"""The usage worker: reads the chat's events from Kafka and keeps usage statistics.

python -m worker          # run the worker (needs KAFKA_BOOTSTRAP_SERVERS)
python -m worker stats    # print the statistics it has built so far

While it runs, its metrics are at http://<host>:9100/metrics (WORKER_METRICS_PORT).
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime
from types import FrameType

from confluent_kafka import Consumer, Message, Producer, TopicPartition
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    start_http_server,
)
from sqlalchemy.orm import sessionmaker

from agent import logs
from worker.usage import BadEvent, apply, make_engine, parse, report

log = logging.getLogger("worker")
TOPIC = "chat-events"
DEAD_LETTERS = "chat-events-dlq"  # messages the worker could not understand
LAG_EVERY = 10.0  # seconds between two lag measurements

disable_created_metrics()  # type: ignore[no-untyped-call]  # see agent/metrics.py

EVENTS = Counter("worker_events", "Events handled, by type and result.", ["type", "result"])
DEAD = Counter("worker_dead_letters", "Messages moved to the dead letter topic.")
LAG = Gauge(
    "worker_consumer_lag", "Events in the topic that this group has not committed.", ["partition"]
)
AGE = Histogram(
    "worker_event_age_seconds",
    "Time from the event happening to the worker applying it.",
    buckets=(0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0, 1800.0),
)


def header(message: Message, name: str) -> str | None:
    """One header of a Kafka message, as text (headers arrive as bytes)."""
    found = message.headers() or []
    for key, value in found.items() if isinstance(found, dict) else found:
        if key == name and value is not None:
            return value.decode() if isinstance(value, bytes) else value
    return None


def measure_lag(consumer: Consumer) -> None:
    """Lag per partition: the newest offset in the topic minus the group's committed one."""
    assigned = consumer.assignment()
    if not assigned:
        return
    for committed in consumer.committed(assigned, timeout=5):
        low, high = consumer.get_watermark_offsets(
            TopicPartition(committed.topic, committed.partition), timeout=5
        )
        done = committed.offset if committed.offset >= 0 else low  # nothing committed yet
        LAG.labels(str(committed.partition)).set(high - done)


def dead_letter(producer: Producer, message: Message, problem: str) -> None:
    """Park a bad message in its own topic, for a person to look at. Then move on."""
    producer.produce(
        DEAD_LETTERS, key=message.key(), value=message.value(), headers={"error": problem}
    )
    producer.flush(10)
    DEAD.inc()
    log.error("dead letter: offset %s: %s", message.offset(), problem)


def run(servers: str, group: str, database_url: str) -> None:
    sessions = sessionmaker(make_engine(database_url))
    consumer = Consumer(
        {
            "bootstrap.servers": servers,
            "group.id": group,  # the group's offsets are kept by Kafka, per partition
            "enable.auto.commit": False,  # we commit ourselves, after the work is done
            "auto.offset.reset": "earliest",  # a new group starts at the oldest event
            "session.timeout.ms": 10000,  # a worker that vanished is noticed after 10 s
            "logger": logging.getLogger("kafka"),  # librdkafka's messages, as JSON lines
        }
    )
    producer = Producer({"bootstrap.servers": servers, "logger": logging.getLogger("kafka")})
    crash = os.getenv("WORKER_CRASH_BEFORE_COMMIT") == "1"  # fault injection, for learning

    running = True

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal running
        running = False  # finish the current event, then leave the group cleanly

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer.subscribe([TOPIC])
    log.info("worker started: group %s, topic %s", group, TOPIC)
    measured = 0.0
    while running:
        if time.monotonic() - measured > LAG_EVERY:
            measure_lag(consumer)
            measured = time.monotonic()
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.warning("kafka: %s", message.error())
            continue
        # The request that caused this event, from its header: our lines carry its id too.
        token = logs.request_id.set(header(message, "request_id"))
        try:
            event = parse(message.value())
        except BadEvent as problem:
            dead_letter(producer, message, str(problem))
        else:
            with sessions.begin() as session:
                applied = apply(session, event)
            result = "applied" if applied else "skipped"
            EVENTS.labels(event["type"], result).inc()
            occurred = datetime.fromisoformat(event.get("occurred_at", ""))
            AGE.observe(max(0.0, time.time() - occurred.timestamp()))
            log.info(
                "partition %s offset %s: %s %s%s",
                message.partition(),
                message.offset(),
                event["type"],
                event["conversation_id"],
                "" if applied else " (seen before: skipped)",
            )
        finally:
            logs.request_id.reset(token)
            if crash:
                log.error("fault injection: crashing before the commit")
                os._exit(1)  # die at once, like a power cut: no cleanup, no commit
        # Done with this message: move the group's offset past it.
        consumer.commit(message=message, asynchronous=False)
    consumer.close()  # leave the group, so its partitions move to another worker at once
    log.info("worker stopped")


def main() -> None:
    logs.setup_logging(os.getenv("CHAT_LOG_LEVEL", "INFO").upper(), "chat-worker")
    database_url = os.getenv("USAGE_DATABASE_URL", "sqlite:///usage.db")
    if sys.argv[1:] == ["stats"]:
        with sessionmaker(make_engine(database_url))() as session:
            for conversation_id, turns, chars in report(session):
                print(f"{conversation_id}  turns {turns:3}  chars {chars:5}")
        return
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        sys.exit("KAFKA_BOOTSTRAP_SERVERS is not set: the worker has nothing to read.")
    start_http_server(int(os.getenv("WORKER_METRICS_PORT", "9100")))  # a thread of its own
    run(servers, os.getenv("WORKER_GROUP", "usage-worker"), database_url)


if __name__ == "__main__":
    main()
