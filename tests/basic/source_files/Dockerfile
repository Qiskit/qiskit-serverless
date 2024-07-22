 FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.12.0-py310

 # install all necessary dependencies for your custom image

 # copy our function implementation in `/runner.py` of the docker image
 USER 0
 RUN  pip install qiskit_aer

 WORKDIR /runner
 COPY tests/basic/source_files/runner.py /runner
 WORKDIR /

 USER $RAY_UID
 


