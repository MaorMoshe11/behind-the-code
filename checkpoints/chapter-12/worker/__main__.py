"""The usage worker: reads the chat's events from Kafka and keeps usage statistics.

python -m worker          # run the worker (needs KAFKA_BOOTSTRAP_SERVERS)
python -m worker stats    # print the statistics it has built so far
"""

import logging
import os
import signal
import sys
from types import FrameType

from confluent_kafka import Consumer, Message, Producer
from sqlalchemy.orm import sessionmaker

from worker.usage import BadEvent, apply, make_engine, parse, report

log = logging.getLogger("worker")
TOPIC = "chat-events"
DEAD_LETTERS = "chat-events-dlq"  # messages the worker could not understand


def dead_letter(producer: Producer, message: Message, problem: str) -> None:
    """Park a bad message in its own topic, for a person to look at. Then move on."""
    producer.produce(
        DEAD_LETTERS, key=message.key(), value=message.value(), headers={"error": problem}
    )
    producer.flush(10)
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
        }
    )
    producer = Producer({"bootstrap.servers": servers})
    crash = os.getenv("WORKER_CRASH_BEFORE_COMMIT") == "1"  # fault injection, for learning

    running = True

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal running
        running = False  # finish the current event, then leave the group cleanly

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer.subscribe([TOPIC])
    log.info("worker started: group %s, topic %s", group, TOPIC)
    while running:
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.warning("kafka: %s", message.error())
            continue
        try:
            event = parse(message.value())
        except BadEvent as problem:
            dead_letter(producer, message, str(problem))
        else:
            with sessions.begin() as session:
                applied = apply(session, event)
            log.info(
                "partition %s offset %s: %s %s%s",
                message.partition(),
                message.offset(),
                event["type"],
                event["conversation_id"],
                "" if applied else " (seen before: skipped)",
            )
            if crash:
                log.error("fault injection: crashing before the commit")
                os._exit(1)  # die at once, like a power cut: no cleanup, no commit
        # Done with this message: move the group's offset past it.
        consumer.commit(message=message, asynchronous=False)
    consumer.close()  # leave the group, so its partitions move to another worker at once
    log.info("worker stopped")


def main() -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    database_url = os.getenv("USAGE_DATABASE_URL", "sqlite:///usage.db")
    if sys.argv[1:] == ["stats"]:
        with sessionmaker(make_engine(database_url))() as session:
            for conversation_id, turns, chars in report(session):
                print(f"{conversation_id}  turns {turns:3}  chars {chars:5}")
        return
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        sys.exit("KAFKA_BOOTSTRAP_SERVERS is not set: the worker has nothing to read.")
    run(servers, os.getenv("WORKER_GROUP", "usage-worker"), database_url)


if __name__ == "__main__":
    main()
