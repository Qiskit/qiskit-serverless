import logging
from typing import Optional

import numpy as np

from qiskit import QuantumCircuit
from qiskit.primitives import BaseSampler, Sampler as QiskitSampler
from qiskit.algorithms.optimizers import SPSA, Optimizer, COBYLA
from qiskit.opflow import PauliSumOp
from qiskit.algorithms.minimum_eigensolvers import QAOA

from qiskit_ibm_runtime import QiskitRuntimeService, Sampler, Session, Options

from quantum_serverless import QuantumServerless, distribute_task, get_arguments, get, save_result


def run_qaoa(
    sampler: BaseSampler,
    optimizer: Optimizer,
    reps: int,
    operator: PauliSumOp
):
    qaoa = QAOA(sampler, optimizer, reps=reps)
    return qaoa.compute_minimum_eigenvalue(operator)


if __name__ == '__main__':
    arguments = get_arguments()
    
    service = arguments.get("service")
    
    operator = arguments.get("operator")
    initial_point = arguments.get("initial_point")
    reps = arguments.get("reps", 1)
    
    optimizers = {
        "spsa": SPSA(),
        "cobyla": COBYLA()
    }
    optimizer = optimizers.get(arguments.get("optimizer", "nan"))
    if optimizer is None:
        raise Exception(
            f"Optimizer {optimizer} is not is a list of available optimizers [{list(optimizers.keys())}]"
        )

    if service is not None:
        # if we have service we need to open a session and create sampler
        service = arguments.get("service")        
        backend = arguments.get("backend", "ibmq_qasm_simulator")
        with Session(service=service, backend=backend) as session:
            options = Options()
            options.optimization_level = 3

            sampler = Sampler(session=session, options=options)
            result = run_qaoa(sampler, optimizer, reps, operator)
    else:
        # if we do not have a service let's use standart local sampler
        sampler = QiskitSampler()
        result = run_qaoa(sampler, optimizer, reps, operator)

    save_result({
        "cost_function_evals": result.cost_function_evals,
        "eigenstate": result.eigenstate,
        "eigenvalue": result.eigenvalue,
        "optimal_parameters": list(result.optimal_parameters.values()),
        "optimal_point": result.optimal_point.tolist(),
        "optimal_value": result.optimal_value,
        "optimizer_time": result.optimizer_time
    })
