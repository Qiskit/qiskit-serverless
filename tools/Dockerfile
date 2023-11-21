FROM icr.io/quantum-public/quantum-serverless-ray-node:0.8.0-py39

WORKDIR /
COPY --chown=$RAY_UID:$RAY_UID ./tools ./qs_tools
WORKDIR /qs_tools
RUN pip install . --no-cache-dir
WORKDIR /
RUN rm -r ./qs_tools
