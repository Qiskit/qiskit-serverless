# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

FROM python:3.11-slim
RUN apt-get update && apt-get install -y s3fs fuse && rm -rf /var/lib/apt/lists/*
# Upgrade the base image build tools to versions without known CVEs
# (CVE-2026-8643 in pip, CVE-2026-24049 in wheel, CVE-2026-59890 in setuptools).
RUN pip install --no-cache-dir --upgrade "pip>=26.1.2" "setuptools>=83.0.0" "wheel>=0.46.2"
COPY client/ /tmp/client/
RUN pip install /tmp/client/ boto3
COPY tests/fleets/fleet-worker/storage.py /app/storage.py
COPY tests/fleets/fleet-worker/worker.py /app/worker.py
COPY tests/fleets/fleet-worker/runner.py /runner/runner.py
ENV PYTHONPATH=/runner
WORKDIR /app
CMD ["python", "worker.py"]
