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
=====================================================
Storage utilities (:mod:`quantum_serverless.utils.storage`)
=====================================================

.. currentmodule:: quantum_serverless.utils.storage

Quantum serverless storage utilities
=================================

.. autosummary::
    :toctree: ../stubs/

    PersistentStorage
"""
import os
import s3fs


class PersistentStorage:
    """Class for storing objects in a non-temporary manner."""

    def __init__(
            self,
            endpoint: str,
            bucket: str
    ):
        """Long-term storage for serverless computation."""
        self.endpoint = endpoint
        self.bucket = bucket
        self.key = os.getenv("ACCESSKEY")
        self.secret = os.getenv("SECRETKEY")
        self.storage = s3fs.core.S3FileSystem(
            endpoint_url=self.endpoint,
            key=self.key,
            secret=self.secret
        )

    def persist_data(self, filename, data):
        """Store data in persistent storage."""
        with self.storage.open(f"{self.bucket}/{filename}", "w") as f:
            f.write(data)

    def retrieve_data(self, filename):
        """Get data from persistent storage."""
        with self.storage.open(f"{self.bucket}/{filename}", "r") as f:
            print(f.read())
