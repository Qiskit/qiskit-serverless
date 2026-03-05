.. _image_examples:

=================================
Example entrypoint and Dockerfile
=================================

Entrypoint example (``runner.py``):

.. code-block::
   :caption: runner.py

   from qiskit_aer import AerSimulator
   from qiskit_serverless import get_arguments, save_result
   from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
   from qiskit_ibm_runtime import Session

   def custom_function(arguments):
        service = arguments.get("service")
        circuit = arguments.get("circuit")
        observable = arguments.get("observable")

        if service:
            backend = service.least_busy(operational=True, simulator=False, min_num_qubits=127)
            session = Session(backend=backend)
        else:
            backend = AerSimulator()

       target = backend.target
       pm = generate_preset_pass_manager(target=target, optimization_level=3)

       target_circuit = pm.run(circuit)
       target_observable = observable.apply_layout(target_circuit.layout)

       from qiskit_ibm_runtime import EstimatorV2 as Estimator
       if service:
           estimator = Estimator(session=session)
       else:
           estimator = Estimator(backend=backend)
       job = estimator.run([(target_circuit, target_observable)])

       if service:
           session.close()
       return job.result()[0].data.evs

   class Runner:
       def run(self, arguments: dict) -> dict:
           return custom_function(arguments)

Dockerfile:

.. code-block::
   :caption: Dockerfile

   FROM icr.io/quantum-public/qiskit-serverless/ray-node:0.29.0

   # install all necessary dependencies for your custom image

   # copy our function implementation in `/runner/runner.py` of the docker image
   USER 0
   RUN  pip install qiskit_aer

   WORKDIR /runner
   COPY ./runner.py /runner
   WORKDIR /

   USER 1000

Follow the steps in the :ref:`deploy_image` section to deploy and run the function using local infrastructure.