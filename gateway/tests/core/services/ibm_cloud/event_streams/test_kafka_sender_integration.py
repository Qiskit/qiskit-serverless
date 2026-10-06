"""Integration test of KafkaSender.send(timeout=0) against a real Kafka broker, in a Docker container.

The mocks in test_kafka_sender.py cannot tell whether librdkafka really delivers without a flush, expires a message
that cannot be delivered, or recovers when the broker comes back. This does.

It starts a single node apache/kafka container (about 240 MB the first time), so it only runs when asked for::

    RUN_KAFKA_INTEGRATION=1 pytest tests/core/services/ibm_cloud/event_streams/test_kafka_sender_integration.py

The producers are the real ones, configured by the real KafkaProducers, except for the SASL_SSL settings, which a
local broker does not have.
"""

import logging
import os
import socket
import subprocess
import time
import uuid
from unittest.mock import patch

import pytest
from confluent_kafka import Producer

from core.ibm_cloud.event_streams import kafka_producers
from core.ibm_cloud.event_streams.kafka_producers import KafkaProducers
from core.ibm_cloud.event_streams.kafka_sender import KafkaSender

IMAGE = "apache/kafka:latest"
CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"
KAFKA_BIN = "/opt/kafka/bin"


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_KAFKA_INTEGRATION") and _docker_available()),
    reason="set RUN_KAFKA_INTEGRATION=1 and have a Docker daemon to run the Kafka integration test",
)


def _docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Broker:
    """A single node Kafka in a container, with one topic."""

    def __init__(self, topic: str):
        self.name = f"kafka-it-{uuid.uuid4().hex[:8]}"
        self.port = _free_port()
        self.topic = topic

    @property
    def bootstrap(self) -> str:
        return f"localhost:{self.port}"

    def start(self) -> None:
        env = {
            "KAFKA_NODE_ID": "1",
            "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": f"PLAINTEXT://:{self.port},CONTROLLER://:9093",
            "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://localhost:{self.port}",
            "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_INTER_BROKER_LISTENER_NAME": "PLAINTEXT",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
            "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
            "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1",
        }
        flags = [flag for key, value in env.items() for flag in ("-e", f"{key}={value}")]
        _docker("run", "-d", "--name", self.name, "-p", f"{self.port}:{self.port}", *flags, IMAGE)
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        for _ in range(60):
            listing = _docker(
                "exec", self.name, f"{KAFKA_BIN}/kafka-topics.sh", "--bootstrap-server", self.bootstrap, "--list",
                check=False,
            )  # fmt: skip
            if listing.returncode == 0:
                return
            time.sleep(2)
        raise RuntimeError("the Kafka container did not become ready")

    def create_topic(self) -> None:
        _docker(
            "exec", self.name, f"{KAFKA_BIN}/kafka-topics.sh", "--bootstrap-server", self.bootstrap,
            "--create", "--topic", self.topic, "--partitions", "1",
        )  # fmt: skip

    def stop(self) -> None:
        _docker("stop", "-t", "1", self.name)

    def restart(self) -> None:
        _docker("start", self.name)
        self._wait_until_ready()
        time.sleep(3)  # let the clients reconnect

    def remove(self) -> None:
        _docker("rm", "-f", self.name, check=False)

    def messages(self) -> int:
        """How many messages the topic holds."""
        offsets = _docker(
            "exec", self.name, f"{KAFKA_BIN}/kafka-get-offsets.sh", "--bootstrap-server", self.bootstrap,
            "--topic", self.topic,
        ).stdout  # fmt: skip
        return sum(int(line.split(":")[-1]) for line in offsets.splitlines() if line)


@pytest.fixture(scope="module")
def broker():
    broker = Broker(topic="quantum.test.function-usage.v1")
    try:
        broker.start()
        broker.create_topic()
        yield broker
    finally:
        broker.remove()


@pytest.fixture
def sender(broker, settings):
    """A KafkaSender whose producers are the real ones, pointed at the container without SASL_SSL."""
    settings.ENVIRONMENT = "test"
    settings.EVENT_STREAMS_BOOTSTRAP_SERVERS = broker.bootstrap
    settings.EVENT_STREAMS_API_KEY = "unused"
    settings.EVENT_STREAMS_USER = "token"
    settings.EVENT_STREAMS_MAIN_REGION = "us-east"
    settings.EVENT_STREAMS_REGIONS = {}
    real_producer = Producer

    def without_sasl(conf):
        conf = {key: value for key, value in conf.items() if not key.startswith("sasl.")}
        conf.update({"security.protocol": "plaintext", "bootstrap.servers": broker.bootstrap, "log_level": 0})
        return real_producer(conf)

    with patch.object(kafka_producers, "Producer", side_effect=without_sasl):
        yield KafkaSender(KafkaProducers())


def _payload(i: int) -> dict:
    return {
        "specversion": "1.0",
        "id": f"evt-{i}",
        "source": "integration-test",
        "subject": f"job-{i}",
        "datacontenttype": "application/json",
        "data": {"metric_value": 1, "instance_crn": CRN},
    }


def _serve_delivery_reports(sender: KafkaSender, seconds: float) -> None:
    """What the next sends of the scheduler do on every call: poll serves the delivery reports."""
    producer = sender._producers.get(CRN)  # pylint: disable=protected-access
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        producer.poll(0.2)


def _wait_for_messages(broker: Broker, expected: int, seconds: float = 15) -> int:
    deadline = time.monotonic() + seconds
    count = broker.messages()
    while count < expected and time.monotonic() < deadline:
        time.sleep(0.5)
        count = broker.messages()
    return count


def test_messages_sent_without_waiting_reach_the_broker(broker, sender, caplog):
    before = broker.messages()

    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        for i in range(200):
            sender.send(_payload(i), timeout=0)
    elapsed = time.monotonic() - started

    assert elapsed < 1, "send(timeout=0) must not wait for the broker"
    assert _wait_for_messages(broker, before + 200) == before + 200
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_an_outage_does_not_block_the_sender_and_it_recovers_when_the_broker_is_back(broker, sender, caplog):
    broker.stop()
    try:
        started = time.monotonic()
        for i in range(200):
            sender.send(_payload(i), timeout=0)
        elapsed = time.monotonic() - started
        assert elapsed < 1, "send(timeout=0) must not wait for a broker that is down"

        # the producer gives up on each message after message.timeout.ms (4 s)
        with caplog.at_level(logging.WARNING):
            _serve_delivery_reports(sender, 8)
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1, "200 dropped messages must be one warning, not one per message"
        assert "dropped" in warnings[0]
        assert "_MSG_TIMED_OUT" in warnings[0]
    finally:
        broker.restart()

    before = broker.messages()
    for i in range(50):
        sender.send(_payload(1000 + i), timeout=0)
    assert _wait_for_messages(broker, before + 50) == before + 50
