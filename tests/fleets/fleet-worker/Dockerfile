FROM python:3.11-slim
RUN apt-get update && apt-get install -y s3fs fuse && rm -rf /var/lib/apt/lists/*
COPY client/ /tmp/client/
RUN pip install /tmp/client/ boto3
COPY tests/fleets/fleet-worker/worker.py /app/worker.py
WORKDIR /app
CMD ["python", "worker.py"]
