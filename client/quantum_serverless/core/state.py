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
===============================================
Provider (:mod:`quantum_serverless.core.state`)
===============================================

.. currentmodule:: quantum_serverless.core.state

Quantum serverless state handler
=================================

.. autosummary::
    :toctree: ../stubs/

    ExecutionMessage
    EventHandler
    RedisEventHandler
"""

from abc import ABC
from typing import Any, Dict, Optional

import json
import redis


class StateHandler(ABC):
    """Base class for state handlers."""

    def set(self, key: str, value: Dict[str, Any]):
        """Sets value by key."""
        raise NotImplementedError

    def get(self, key: str):
        """Gets value by key."""
        raise NotImplementedError


class RedisStateHandler(StateHandler):
    """RedisStateHandler."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = None,  # pylint: disable=invalid-name
        password: str = None,
    ):
        """RedisStateHandler.

        Example:
            >>> state = RedisStateHandler(
            >>>     host="<REDIS_HOST>",
            >>>     port=8267,
            >>>     password="<REDIS_PASSWORD>"
            >>> )
            >>> state.set("some_id", {"some_key": "some_value"})
            >>> state.get("some_id")
            >>> # {"some_key": "some_value"}

        Args:
            host: host for redis database
            port: port for redis
            db: database
            password: redis password
        """
        # TODO: initialization using env variables  # pylint: disable=fixme
        self._host = host or "localhost"
        self._port = port or 6379
        self._db = db if db is not None else 0
        self._password = password
        self._redis = redis.Redis(
            host=self._host, port=self._port, db=self._db, password=self._password
        )

    def set(self, key: str, value: Dict[str, Any]):
        return self._redis.set(key, json.dumps(value))

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        value = self._redis.get(key)
        if value:
            return json.loads(value)
        return None

    def __reduce__(self):
        deserializer = RedisStateHandler
        serialized_data = (self._host, self._port, self._db, self._password)
        return deserializer, serialized_data

    def __repr__(self):
        return f"<RedisStateHandler | {self._host}:{self._port}>"
