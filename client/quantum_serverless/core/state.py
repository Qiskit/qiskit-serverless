"""State handler."""
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
