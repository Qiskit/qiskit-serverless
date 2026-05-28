FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.30.0

USER 0
WORKDIR /runner
COPY ./custom-image/runner.py /runner
COPY ./client /tmp/qiskit-serverless-client
RUN pip install --no-cache-dir /tmp/qiskit-serverless-client && rm -rf /tmp/qiskit-serverless-client
WORKDIR /
USER 1000