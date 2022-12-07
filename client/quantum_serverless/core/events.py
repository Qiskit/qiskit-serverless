# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
================================================
Provider (:mod:`quantum_serverless.core.events`)
================================================

.. currentmodule:: quantum_serverless.core.events

Quantum serverless events handler
=================================

.. autosummary::
    :toctree: ../stubs/

    ExecutionMessage
    EventHandler
    RedisEventHandler
"""

import json
import os
import time
from abc import ABC
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Iterator, List, Union

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


class EventHandler(ABC):
    """Base class for events handling."""

    def publish(self, topic: str, message: Dict[str, Any]):
        """Emits message to specified topic."""
        raise NotImplementedError

    def subscribe(self, topic: Union[str, bytes]):
        """Subscribe to given list of topics."""
        raise NotImplementedError

    def unsubscribe(self, topics: Optional[List[str]] = None):
        """Unsubscribe from topics."""
        raise NotImplementedError

    def listen(self) -> Iterator[Dict[str, Any]]:
        """Returns iterator of messages that handler is subscribed to."""
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

        Example:
            >>> emitter = RedisEventHandler(
            >>>     host="<REDIS_HOST>",
            >>>     port=8267,
            >>>     password="<REDIS_PASSWORD>"
            >>> )
            >>> emitter.publish("some_topic", {"some_key": "some_value"})

        Example:
            >>> emitter = RedisEventHandler.from_env_vars()
            >>> # if env variables are set it will create handler object
            >>> # otherwise return None
            >>> if emitter is not None:
            >>>     emitter.publish("some_topic", {"some_key": "some_value"})

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
        self.pubsub = self.redis.pubsub()

    def publish(self, topic: str, message: Dict[str, Any]):
        return self.redis.publish(topic, json.dumps(message))

    def subscribe(self, topic: Union[str, bytes]):
        return self.pubsub.subscribe(topic)

    def unsubscribe(self, topics: Optional[List[str]] = None):
        if topics is not None:
            for topic in topics:
                self.pubsub.unsubscribe(topic)
        else:
            self.pubsub.unsubscribe()

    def listen(self) -> Iterator[Dict[str, Any]]:
        return self.pubsub.listen()

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

    def __reduce__(self):
        deserializer = RedisEventHandler
        serialized_data = (self.host, self.port, self.database, self.password)
        return deserializer, serialized_data
