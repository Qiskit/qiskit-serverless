from qiskit_aer import AerSimulator
import logging
from typing import Optional
import time
import numpy as np
from scipy.optimize import minimize

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import (
    EstimatorV2 as Estimator,
    SamplerV2 as Sampler,
    QiskitRuntimeService,
    Session,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_serverless import (
    distribute_task,
    get_arguments,
    get,
    save_result,
)

def build_callback(ansatz, hamiltonian, estimator, callback_dict):
    """Return callback function that uses Estimator instance,
    and stores intermediate values into a dictionary.

    Parameters:
        ansatz (QuantumCircuit): Parameterized ansatz circuit
        hamiltonian (SparsePauliOp): Operator representation of Hamiltonian
        estimator (Estimator): Estimator primitive instance
        callback_dict (dict): Mutable dict for storing values

    Returns:
        Callable: Callback function object
    """

    def callback(current_vector):
        """Callback function storing previous solution vector,
        computing the intermediate cost value, and displaying number
        of completed iterations and average time per iteration.

        Values are stored in pre-defined 'callback_dict' dictionary.

        Parameters:
            current_vector (ndarray): Current vector of parameters
                                      returned by optimizer
        """
        # Keep track of the number of iterations
        callback_dict["iters"] += 1
        # Set the prev_vector to the latest one
        callback_dict["prev_vector"] = current_vector
        # Compute the value of the cost function at the current vector
        callback_dict["cost_history"].append(
            estimator.run([(ansatz, hamiltonian, current_vector)])
            .result()[0]
        )
        # Grab the current time
        current_time = time.perf_counter()
        # Find the total time of the execute (after the 1st iteration)
        if callback_dict["iters"] > 1:
            callback_dict["_total_time"] += current_time - callback_dict["_prev_time"]
        # Set the previous time to the current time
        callback_dict["_prev_time"] = current_time
        # Compute the average time per iteration and round it
        time_str = (
            round(callback_dict["_total_time"] / (callback_dict["iters"] - 1), 2)
            if callback_dict["_total_time"]
            else "-"
        )
        # Print to screen on single line
        print(
            "Iters. done: {} [Avg. time per iter: {}]".format(
                callback_dict["iters"], time_str
            ),
            end="\r",
            flush=True,
        )

    return callback


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
    energy = (
        estimator.run([(ansatz, hamiltonian, params)]).result()[0].data.evs
    )
    return energy


def run_vqe(initial_parameters, ansatz, operator, estimator, method):
    callback_dict = {
        "prev_vector": None,
        "iters": 0,
        "cost_history": [],
        "_total_time": 0,
        "_prev_time": None,
    }
    callback = build_callback(ansatz, operator, estimator, callback_dict)
    result = minimize(
        cost_func,
        initial_parameters,
        args=(ansatz, operator, estimator),
        method=method,
        callback=callback,
    )
    return result, callback_dict


if __name__ == "__main__":
    arguments = get_arguments()

    service = arguments.get("service")

    ansatz = arguments.get("ansatz")
    operator = arguments.get("operator")
    method = arguments.get("method", "COBYLA")
    initial_parameters = arguments.get("initial_parameters")
    if service:
        backend = service.least_busy(operational=True, simulator=False)
    else:
        backend = AerSimulator()
    if initial_parameters is None:
        initial_parameters = 2 * np.pi * np.random.rand(ansatz.num_parameters)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    ansatz_isa = pm.run(ansatz)
    operator_isa = operator.apply_layout(ansatz_isa.layout)

    if service:
        with Session(service=service, backend=backend) as session:
            estimator = Estimator(session=session)
            vqe_result, callback_dict = run_vqe(
                initial_parameters=initial_parameters,
                ansatz=ansatz_isa,
                operator=operator_isa,
                estimator=estimator,
                method=method,
            )
    else:
        estimator = Estimator(backend=backend)
        vqe_result, callback_dict = run_vqe(
            initial_parameters=initial_parameters,
            ansatz=ansatz_isa,
            operator=operator_isa,
            estimator=estimator,
            method=method,
        )


    qc = ansatz.assign_parameters(vqe_result.x)
    qc.measure_all()
    qc_isa = pm.run(qc)

    if service:
        with Session(service=service, backend=backend) as session:
            sampler = Sampler(session=session)
            samp_dist = sampler.run([qc_isa], shots=int(1e4)).result()[0].data.meas.get_counts()
    else:
        sampler = Sampler(backend=backend)
        samp_dist = sampler.run([qc_isa], shots=int(1e4)).result()[0].data.meas.get_counts()

    save_result(
        {
            "result": samp_dist,
            "optimal_point": vqe_result.x.tolist(),
            "optimal_value": vqe_result.fun,
            "optimizer_time": callback_dict.get("_total_time", 0),
        }
    )
