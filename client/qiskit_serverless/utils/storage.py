# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
===========================================================
Storage utilities (:mod:`qiskit_serverless.utils.storage`)
===========================================================

.. currentmodule:: qiskit_serverless.utils.storage

Qiskit Serverless storage utilities
====================================

.. autosummary::
    :toctree: ../stubs/

    PersistentStorage
"""
from io import BytesIO
import os
from typing import Optional

from abc import abstractmethod
import s3fs


class BaseStorage:
    """Base class for persistent storage."""

    @abstractmethod
    def save(self, path: str, data: BytesIO):
        """Save data."""
        raise NotImplementedError

    @abstractmethod
    def load(self, path: str):
        """Load data."""
        raise NotImplementedError


class S3Storage(BaseStorage):
    """Class for storing s3 objects in a non-temporary manner."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        key: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        """Long-term storage for serverless computation."""
        self.endpoint = endpoint
        self.bucket = bucket
        self.key = key or os.getenv("AWS_ACCESS_KEY")
        self.secret = secret or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.storage = s3fs.core.S3FileSystem(
            endpoint_url=self.endpoint, key=self.key, secret=self.secret
        )

    def save(self, path, data):
        """Store binary data in persistent storage."""
        with self.storage.open(f"{self.bucket}/{path}", "wb") as f:
            f.write(data)

    def load(self, path):
        """Get binary data from persistent storage."""
        with self.storage.open(f"{self.bucket}/{path}", "rb") as f:
            print(f.read())
