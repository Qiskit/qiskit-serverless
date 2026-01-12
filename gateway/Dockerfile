ARG MICRO_IMAGE_DIR=/ubi-micro-img

# BASE image using UBI 9 micro where the
# application and requirements will be installed
FROM registry.access.redhat.com/ubi9-micro:9.7-1762965531 AS base

# BUILD image using UBI 9 where the dependencies that
# require installing with a package manager will be installed
FROM registry.access.redhat.com/ubi9:9.7-1763340522 AS build
ARG MICRO_IMAGE_DIR

# Copy the BASE image into the BUILD image
RUN mkdir ${MICRO_IMAGE_DIR}
COPY --from=base / ${MICRO_IMAGE_DIR}

# Update internal dependencies
RUN dnf update -y && dnf clean all

# Install Python inside the BASE image
RUN dnf install --installroot ${MICRO_IMAGE_DIR} --nodocs -y \
    python3.11 \
    python3.11-devel \
    libstdc++ &&\
    dnf upgrade --installroot ${MICRO_IMAGE_DIR} --nodocs -y && \
    dnf clean all --installroot ${MICRO_IMAGE_DIR}

# APP image from `scratch` which will be the final image
# and remaining application requirements will be installed
FROM scratch AS app
ARG MICRO_IMAGE_DIR
COPY --from=build ${MICRO_IMAGE_DIR}/ .

# create symlinks for python
RUN ln -s /usr/bin/python3.11 /usr/bin/python

# Create project dir
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Add environment variables to set swagger-ui to not send analytics data
ENV SCARF_ANALYTICS=false \
    DO_NOT_TRACK=1

COPY gateway/requirements.txt .

# Install pip, dependencies, and uninstall pip (not needed in final image)
RUN python3.11 -m ensurepip --upgrade && \
    python3.11 -m pip install --upgrade --no-cache-dir setuptools>=80.0.0 && \
    python3.11 -m pip install -r requirements.txt --no-cache-dir --upgrade && \
    cp -r -n /usr/local/lib64/python3.11/site-packages/symengine /usr/local/lib/python3.11/site-packages && \
    cp -r -n /usr/local/lib/python3.11/site-packages/symengine /usr/local/lib64/python3.11/site-packages && \
    python3.11 -m pip uninstall -y pip

COPY --chown=1000:100 gateway .

# Copy dynamic dependencies from Ray node image, used by GET /api/v1/dependencies-versions/
COPY --chown=1000:100 ray-node/requirements-dynamic-dependencies.txt /

RUN mkdir /usr/src/app/media && chown 1000:100 /usr/src/app/media

RUN sed -i 's/\r$//g' /usr/src/app/entrypoint.sh && \
    chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8000
USER 1000:100
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
