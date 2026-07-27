# syntax=docker/dockerfile:1.17
FROM registry.access.redhat.com/ubi9-minimal:9.8-1784092902 AS base
ARG PYTHON_VERSION=3.12

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies and setup Python symlinks
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
# Create data directories and upgrade pip/setuptools
# /data and /function_data are used by the Ray runner as PDS mount points.
# /function_user_data, /job_user_data, /function_provider_data and /job_provider_data
# are used by the Fleets runner (4-mount COS path layout).
RUN mkdir /data /function_data /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    chown 1000:1000 /data /function_data /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    python${PYTHON_VERSION} -m ensurepip --upgrade && \
    pip install --upgrade --no-cache-dir \
        "pip>=24.2" \
        "setuptools>=80.0.0"

# Install latest version of client (at the end for better layer cache usage).
# Ray is an optional extra of the client; the Ray node needs it, so install [ray].
COPY client /tmp/qs
RUN pip install "/tmp/qs[ray]" --no-cache-dir && rm -rf /tmp/qs
USER 1000

FROM base AS selector
USER 0
COPY ray-node/requirements-dynamic-dependencies.txt /tmp/
RUN pip install -r /tmp/requirements-dynamic-dependencies.txt --no-cache-dir && \
    rm /tmp/requirements-dynamic-dependencies.txt
USER 1000

# arm64-native variant for LOCAL DEV on Apple Silicon (M-series) Macs.
# Build with: --target arm64 --platform linux/arm64
#
# Why: the published ray-node image is amd64-only, so on Apple Silicon it runs under QEMU
# emulation. Ray 2.55's dashboard subprocess-modules must report ready within hardcoded ~30s
# startup windows; under emulation they time out, the jobs API never becomes available, and
# jobs stay stuck in QUEUED. Running a NATIVE arm64 image removes the emulation overhead so
# the default timeouts are satisfied. The Ray version is unchanged.
#
# ffsim / qiskit-addon-aqc-tensor are omitted (no arm64 wheels); see
# requirements-dynamic-dependencies-arm64.txt. To restore them, install a Rust toolchain
# so ffsim compiles from source:
#   RUN microdnf install -y gcc gcc-c++ make && microdnf clean all && \
#       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
#   ENV PATH="/root/.cargo/bin:${PATH}"
# and add the two packages back to requirements-dynamic-dependencies-arm64.txt.
FROM base AS arm64
USER 0
COPY ray-node/requirements-dynamic-dependencies-arm64.txt /tmp/requirements-dynamic-dependencies.txt
RUN pip install -r /tmp/requirements-dynamic-dependencies.txt --no-cache-dir && \
    rm /tmp/requirements-dynamic-dependencies.txt
USER 1000
