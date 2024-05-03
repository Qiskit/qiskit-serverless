FROM python:3.10.12-slim-buster

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get -y update && apt-get install  --no-install-recommends -y iptables=1.8.2-4 &&\
    apt-get clean &&\
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip==24.0 --no-cache-dir

RUN adduser --disabled-password --gecos '' worker &&\
    adduser worker

USER worker
WORKDIR /home/worker

COPY --chown=worker:worker proxy/requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

ENV PATH="/home/worker/.local/bin:${PATH}"

COPY --chown=worker:worker proxy/proxy .
RUN chmod +x /home/worker/entrypoint.sh

EXPOSE 8443
ENTRYPOINT ["/home/worker/entrypoint.sh"]
