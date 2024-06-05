FROM icr.io/quantum-public/qiskit-serverless-ray-node:0.11.0-py310

WORKDIR /
COPY --chown=$RAY_UID:$RAY_UID ./tools ./qs_tools
WORKDIR /qs_tools
RUN pip install . --no-cache-dir
WORKDIR /
RUN rm -r ./qs_tools

USER $RAY_UID
