import logging
from typing import Optional

import numpy as np

from qiskit import QuantumCircuit
from qiskit.primitives import BaseEstimator, Estimator as QiskitEstimator
from qiskit.algorithms.optimizers import SPSA, Optimizer
from qiskit.opflow import PauliSumOp
from qiskit.algorithms.minimum_eigensolvers import VQE

from qiskit_ibm_runtime import QiskitRuntimeService, Estimator, Session, Options

from quantum_serverless import QuantumServerless, distribute_task, get_arguments, get, save_result


def run_vqe(
    estimator: BaseEstimator,
    ansatz: QuantumCircuit,
    operator: PauliSumOp,
    optimizer: Optimizer,
    initial_parameters: Optional[np.ndarray] = None
):
    vqe = VQE(
        estimator,
        ansatz,
        optimizer,
        initial_point=initial_parameters,
        callback=lambda idx, parameters, mean, std: print(f"{idx}: {mean}")
    )
    return vqe.compute_minimum_eigenvalue(operator)


if __name__ == '__main__':
    arguments = get_arguments()
    
    service = arguments.get("service")
    
    ansatz = arguments.get("ansatz")
    operator = arguments.get("operator")
    initial_parameters = arguments.get("initial_parameters")
    
    optimizers = {
        "spsa": SPSA()
    }
    optimizer = optimizers.get(arguments.get("optimizer", "nan"))
    if optimizer is None:
        raise Exception(
            f"Optimizer {optimizer} is not is a list of available optimizers [{list(optimizers.keys())}]"
        )

    aux_operators = arguments.get("aux_operators")
    if aux_operators is not None:
        logging.warning("`aux_operators` are not supported yet.")
        
    if service is not None:
        # if we have service we need to open a session and create estimator
        service = arguments.get("service")        
        backend = arguments.get("backend", "ibmq_qasm_simulator")
        with Session(service=service, backend=backend) as session:
            options = Options()
            options.optimization_level = 3

            estimator = Estimator(session=session, options=options)
            vqe_result = run_vqe(
                estimator=estimator,
                ansatz=ansatz,
                operator=operator,
                optimizer=optimizer,
                initial_parameters=initial_parameters
            )
    else:
        # if we do not have a service let's use standart local estimator
        estimator = QiskitEstimator()
        vqe_result = run_vqe(
            estimator=estimator,
            ansatz=ansatz,
            operator=operator,
            optimizer=optimizer,
            initial_parameters=initial_parameters
        )

    save_result({
        "aux_operator_eigenvalues": [],
        "cost_function_evals": vqe_result.cost_function_evals,
        "eigenstate": None,
        "eigenvalue": vqe_result.eigenvalue,
        "optimal_parameters": None,
        "optimal_point": vqe_result.optimal_point.tolist(),
        "optimal_value": vqe_result.optimal_value,
        "optimizer_evals": vqe_result.optimizer_evals,
        "optimizer_history": {},
        "optimizer_time": vqe_result.optimizer_time
    })
