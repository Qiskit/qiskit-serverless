ARG MICRO_IMAGE_DIR=/ubi-micro-img

# BASE image using UBI 9 micro where the
# application and requirements will be installed
FROM registry.access.redhat.com/ubi9-micro:9.4-15 AS BASE

# BUILD image using UBI 9 where the dependencies that
# require installing with a package manager will be installed
FROM registry.access.redhat.com/ubi9:9.4-1214.1726694543 AS BUILD
ARG MICRO_IMAGE_DIR

# Copy the BASE image into the BUILD image
RUN mkdir ${MICRO_IMAGE_DIR}
COPY --from=BASE / ${MICRO_IMAGE_DIR}

# Install Python inside the BASE image
# hadolint ignore=DL3041
RUN dnf install --installroot ${MICRO_IMAGE_DIR} --nodocs -y \
    python3.11-3.11.7 \
    python3.11-devel-3.11.7 \
    libstdc++ &&\
    dnf upgrade --installroot ${MICRO_IMAGE_DIR} --nodocs -y && \
    dnf clean all --installroot ${MICRO_IMAGE_DIR}

# APP image from `scratch` which will be the final image
# and remaining application requirements will be installed
FROM scratch AS APP
ARG MICRO_IMAGE_DIR
# hadolint ignore=DL3045
COPY --from=BUILD ${MICRO_IMAGE_DIR}/ .

# create symlinks for python
RUN ln -s /usr/bin/python3.11 /usr/bin/python

# Create project dir
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY gateway/requirements.txt .
# Install pip
RUN python3.11 -m ensurepip --upgrade
# Install dependencies and update then uninstall pip (not needed in final image)
RUN python3.11 -m pip install -r requirements.txt --no-cache-dir --upgrade && \
    cp -r -n /usr/local/lib64/python3.11/site-packages/symengine /usr/local/lib/python3.11/site-packages &&\
    cp -r -n /usr/local/lib/python3.11/site-packages/symengine /usr/local/lib64/python3.11/site-packages &&\
    python3.11 -m pip uninstall -y pip

COPY gateway .
RUN chown -R 1000:100 /usr/src/app &&\
    mkdir /usr/src/app/media && chown 1000:100 /usr/src/app/media

RUN sed -i 's/\r$//g' /usr/src/app/entrypoint.sh &&\
    chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8000
USER 1000:100
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
