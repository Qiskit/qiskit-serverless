"""Events manager."""
import json
import os
import time
from abc import ABC
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

import redis

from quantum_serverless.core.constrants import (
    QS_EVENTS_REDIS_PASSWORD,
    QS_EVENTS_REDIS_PORT,
    QS_EVENTS_REDIS_HOST,
)


@dataclass
class ExecutionMessage:
    """ExecutionMessage class for meta information about function execution."""

    workload_id: str
    uid: str
    layer: str
    resources: Dict[str, float]
    function_meta: Dict[str, Any]
    timestamp: float = time.time()

    def to_dict(self):
        """Converts to dictionary."""
        return asdict(self)

    def __repr__(self):
        return f"<ExecutionMessage | {self.workload_id}|{self.layer}>"


class EventHandler(ABC):  # pylint: disable=too-few-public-methods
    """Base class for events handling."""

    def publish(self, topic: str, message: Dict[str, Any]):
        """Emits message to specified topic."""
        raise NotImplementedError


class RedisEventHandler(EventHandler):
    """RedisEventHandler."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[int] = None,
        password: Optional[str] = None,
    ):
        """Event handler backed up by Redis.

        Args:
            host: redis host
            port: redis port
            database: redis db
            password: redis password
        """
        self.host = host or "localhost"
        self.port = port or 6379
        self.database = database if database is not None else 0
        self.password = password
        self.redis = redis.Redis(
            host=self.host, port=self.port, db=self.database, password=self.password
        )

    def publish(self, topic: str, message: Dict[str, Any]):
        return self.redis.publish(topic, json.dumps(message))

    @classmethod
    def from_env_vars(cls) -> Optional["RedisEventHandler"]:
        """Creates handler from env variables."""
        host = os.environ.get(QS_EVENTS_REDIS_HOST, None)
        port = os.environ.get(QS_EVENTS_REDIS_PORT, None)
        if host is None and port is None:
            return None

        return cls(
            host,
            int(port),
            database=0,
            password=os.environ.get(QS_EVENTS_REDIS_PASSWORD, None),
        )
