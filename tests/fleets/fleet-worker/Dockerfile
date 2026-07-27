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
#
# Mock Code Engine fleet worker for the fleets integration tests. Builds on the
# real fleets runtime base (fleet-node) so the test exercises the same image
# production fleet tasks run in, then adds only the harness-specific bits:
# s3fs/fuse to mock CE's COS mount against MinIO, boto3, and the worker scripts.
#
# BASE_IMAGE must be built first (e.g. `make build-fleet-node` or the CI
# "Build fleet-node base image" step) and tagged fleet-node:latest.
ARG BASE_IMAGE=fleet-node:latest
FROM ${BASE_IMAGE}

# Root: s3fs needs microdnf + FUSE mounts at runtime (compose runs this privileged).
USER 0

# s3fs-fuse lives in EPEL (not the ubi9 base repos). microdnf can't install from a
# URL, so fetch the EPEL9 release RPM with curl and install it via rpm (both ship in
# ubi9-minimal), which registers the repo; then microdnf can resolve s3fs-fuse + fuse.
# -f: fail (non-zero) on an HTTP error instead of saving the error page and letting
# a later `rpm -Uvh` fail confusingly; --retry: tolerate transient mirror hiccups.
RUN curl -fSL --retry 3 --retry-delay 2 --retry-all-errors \
        -o /tmp/epel.rpm https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    rpm -Uvh /tmp/epel.rpm && \
    rm -f /tmp/epel.rpm && \
    microdnf install -y s3fs-fuse fuse && \
    microdnf clean all

# boto3 for the worker's MinIO/COS access. The client and patched pip/setuptools
# already come from the base image (fleet-node), so no build-tool re-upgrade here.
RUN pip install --no-cache-dir boto3

COPY tests/fleets/fleet-worker/storage.py /app/storage.py
COPY tests/fleets/fleet-worker/worker.py /app/worker.py
COPY tests/fleets/fleet-worker/runner.py /runner/runner.py
ENV PYTHONPATH=/runner
WORKDIR /app
CMD ["python", "worker.py"]
