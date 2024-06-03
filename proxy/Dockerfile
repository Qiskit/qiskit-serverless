FROM registry.access.redhat.com/ubi9/python-311

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0
RUN mkdir /home/worker
WORKDIR /home/worker

ENV PATH="/home/worker/.local/bin:${PATH}"

COPY --chown=1000:100 proxy/requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY --chown=1000:100 proxy/proxy .
RUN chmod +x /home/worker/entrypoint.sh

USER 1000:100
EXPOSE 8443
ENTRYPOINT ["/home/worker/entrypoint.sh"]
