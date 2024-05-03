FROM python:3.10.12-slim-buster

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN  adduser --disabled-password --gecos '' worker

USER worker
WORKDIR /home/worker

ENV PATH="/home/worker/.local/bin:${PATH}"

COPY --chown=worker:worker proxy/requirements.txt .
# hadolint ignore=DL3013
RUN pip install --upgrade pip --no-cache-dir &&\
    pip install -r requirements.txt --no-cache-dir

COPY --chown=worker:worker proxy/proxy .
RUN chmod +x /home/worker/entrypoint.sh

EXPOSE 8443
ENTRYPOINT ["/home/worker/entrypoint.sh"]
