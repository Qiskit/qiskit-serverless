# syntax=docker/dockerfile:1.17
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
# Fleets worker base image (Python 3.12) — the Fleets-runner counterpart of
# ray-node/Dockerfile. This is the runtime image Code Engine fleet tasks run in;
# the integration-test worker (tests/fleets/fleet-worker/Dockerfile) builds FROM it.
#
# Build from repo root (client/ and ray-node/ must be in the build context):
#   docker build --platform linux/amd64 -f fleet-node/Dockerfile -t fleet-node:latest .
#
# No CUDA base: nothing here links against CUDA (qiskit-aer is the CPU build),
# and CE's NVIDIA container runtime injects the driver + nvidia-smi into GPU
# workers at runtime. UBI9 (glibc 2.34) satisfies the mthree manylinux_2_34 wheel;
# all pinned deps ship linux/x86_64 wheels for 3.12, so no build toolchain is needed.
FROM registry.access.redhat.com/ubi9-minimal:9.8-1784092902
ARG PYTHON_VERSION=3.12
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python and set up interpreter/pip symlinks (all bound to ${PYTHON_VERSION}).
RUN microdnf update -y && \
    microdnf install -y \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-devel \
        wget-1.21.1 && \
    microdnf clean all && \
    ln -s /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3 && \
    ln -s /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python && \
    ln -s /usr/bin/pip${PYTHON_VERSION} /usr/local/bin/pip3 && \
    ln -s /usr/bin/pip${PYTHON_VERSION} /usr/local/bin/pip

USER 0
# /function_user_data, /job_user_data, /function_provider_data, /job_provider_data
# are the Fleets runner 4-mount COS path layout. fleet-node runs Fleets jobs only,
# so it does not create the Ray runner's /data and /function_data mounts.
#
# pip/setuptools floors clear known CVEs (CVE-2026-8643 in pip,
# CVE-2026-59890 in setuptools); images built FROM this inherit them. wheel is
# intentionally not installed (ubi9 ensurepip omits it; nothing here builds from
# an sdist), so CVE-2026-24049 in wheel does not apply.
# NOTE: keep this a plain '&&' chain — do not put '#' comments between the
# continued commands, or a broken chain could silently skip the pip upgrade.
RUN mkdir /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    chown 1000:1000 /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    python${PYTHON_VERSION} -m ensurepip --upgrade && \
    pip install --upgrade --no-cache-dir \
        "pip>=26.1.2" \
        "setuptools>=83.0.0"

# Dynamic dependencies — the qiskit workload stack pre-baked so Fleets functions
# run without reinstalling. Kept in fleet-node's own file (not shared with
# ray-node) so the two runners can evolve independently; today the set is the
# same as ray-node's. All resolve to prebuilt 3.12 wheels.
COPY fleet-node/requirements-dynamic-dependencies.txt /tmp/
RUN pip install --no-cache-dir \
        -r /tmp/requirements-dynamic-dependencies.txt && \
    rm /tmp/requirements-dynamic-dependencies.txt

# Install the client last for better layer-cache reuse. Keep this on its own RUN
# with plain '&&' so a failed install fails the build — do NOT chain '|| true'
# guards onto this step (that would silently ship an image with no client).
# (No symengine lib/lib64 copy: Qiskit 2.2 dropped symengine, so it is not
# installed here; ray-node/gateway removed the same copy in 0.34.0.)
COPY client /tmp/qs
RUN pip install --no-cache-dir /tmp/qs && \
    rm -rf /tmp/qs

USER 1000
