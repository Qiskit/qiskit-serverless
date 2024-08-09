FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.15.0

WORKDIR /
USER 0
COPY --chown=$RAY_UID:$RAY_UID ./tools ./qs_tools
WORKDIR /qs_tools
RUN pip install . --no-cache-dir
WORKDIR /
RUN rm -r ./qs_tools

USER 1000
