import logging
import os
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from qiskit import QuantumCircuit
from qiskit.primitives import BaseEstimator, Estimator as QiskitEstimator
from qiskit.quantum_info import SparsePauliOp
from qiskit.circuit.library import QAOAAnsatz
from qiskit_ibm_runtime import QiskitRuntimeService, Estimator, Session, Options

from quantum_serverless import (
    QuantumServerless,
    distribute_task,
    get_arguments,
    get,
    save_result,
)


def cost_func(params, ansatz, hamiltonian, estimator):
    """Return estimate of energy from estimator

    Parameters:
        params (ndarray): Array of ansatz parameters
        ansatz (QuantumCircuit): Parameterized ansatz circuit
        hamiltonian (SparsePauliOp): Operator representation of Hamiltonian
        estimator (Estimator): Estimator primitive instance

    Returns:
        float: Energy estimate
    """
    print(os.environ)
    cost = (
        estimator.run(ansatz, hamiltonian, parameter_values=params).result().values[0]
    )
    return cost


def run_qaoa(
    ansatz: QuantumCircuit,
    estimator: BaseEstimator,
    operator: SparsePauliOp,
    initial_point: np.array,
    method: str,
):
    return minimize(
        cost_func, initial_point, args=(ansatz, operator, estimator), method=method
    )


if __name__ == "__main__":
    arguments ={
        'initial_point': None,
        'operator': SparsePauliOp(
            ['IIIZZ', 'IIZIZ', 'IZIIZ', 'ZIIIZ'],
            coeffs=[1.+0.j, 1.+0.j, 1.+0.j, 1.+0.j]
        ),
        'backend': 'ibmq_qasm_simulator',
    }

    service = QiskitRuntimeService(
        channel='ibm_quantum',
        instance='ibm-q/open/main',
        token='45e8a763ccfb5a7a60e3b8cffd25677e866e2271214ea288fd0f68a996c8b027d91a769c9900cc3b41f2f1bd7e608be214a5d795c5d2fb5e9a5d420470a13b6e'
    )

    operator = arguments.get("operator")
    ansatz = QAOAAnsatz(operator, reps=2)
    ansatz = ansatz.decompose(reps=3)
    ansatz.draw(fold=-1)
    initial_point = arguments.get("initial_point")
    method = arguments.get("method", "COBYLA")

    if initial_point is None:
        initial_point = 2 * np.pi * np.random.rand(ansatz.num_parameters)

    if service is not None:
        # if we have service we need to open a session and create sampler
        service = arguments.get("service")
        backend = arguments.get("backend", "ibmq_qasm_simulator")
        session = Session(service=service, backend=backend)
        print("session")
        print(session)
        print(session.status())
        options = Options()
        options.optimization_level = 3

        estimator = Estimator(session=session, options=options)
        print(session.status())
    else:
        # if we do not have a service let's use standart local sampler
        estimator = QiskitEstimator()

    result = run_qaoa(ansatz, estimator, operator, initial_point, method)

    save_result({"optimal_point": result.x.tolist(), "optimal_value": result.fun})
