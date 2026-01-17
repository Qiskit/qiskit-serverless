# syntax=docker/dockerfile:1.17
FROM registry.access.redhat.com/ubi9-minimal:9.7-1763362218
ARG DYNAMIC_DEPENDENCIES_FILE
# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies and setup Python symlinks
RUN microdnf update -y && \
    microdnf install -y \
        python3.11 \
        python3.11-devel \
        wget-1.21.1 && \
    microdnf clean all && \
    ln -s /usr/bin/python3.11 /usr/local/bin/python3 && \
    ln -s /usr/bin/python3.11 /usr/local/bin/python && \
    ln -s /usr/bin/pip3.11 /usr/local/bin/pip3 && \
    ln -s /usr/bin/pip3.11 /usr/local/bin/pip


USER 0
# Create data directories and upgrade pip/setuptools
RUN mkdir /data /function_data && \
    chown 1000:1000 /data /function_data && \
    python3.11 -m ensurepip --upgrade && \
    pip install --upgrade --no-cache-dir \
        "pip>=24.2" \
        "setuptools>=80.0.0"

# Install dynamic dependencies (if specified)
COPY ray-node/requirements-dynamic-dependencies.txt /tmp/
COPY ray-node/requirements-test-dynamic-dependencies.txt /tmp/
RUN if [ -n "${DYNAMIC_DEPENDENCIES_FILE}" ]; then \
        pip install -r /tmp/${DYNAMIC_DEPENDENCIES_FILE} --no-cache-dir; \
    fi

# Install latest version of client (at the end for better layer cache usage)
COPY client /tmp/qs
RUN pip install /tmp/qs --no-cache-dir
RUN cp -r -n /usr/local/lib64/python3.11/site-packages/symengine /usr/local/lib/python3.11/site-packages && \
    cp -r -n /usr/local/lib/python3.11/site-packages/symengine /usr/local/lib64/python3.11/site-packages && \
    rm -rf /tmp/qs /tmp/requirements*.txt

USER 1000
