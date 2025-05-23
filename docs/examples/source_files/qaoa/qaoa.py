from qiskit_aer import AerSimulator
# General imports
import numpy as np

# Pre-defined ansatz circuit, operator class and visualization tools
from qiskit import QuantumCircuit
from qiskit.circuit.library import QAOAAnsatz
from qiskit.quantum_info import SparsePauliOp

from qiskit.primitives import BaseEstimatorV1 as BaseEstimator
from qiskit_ibm_runtime import QiskitRuntimeService, Session
from qiskit_ibm_runtime import EstimatorV2 as Estimator
from qiskit_ibm_runtime import SamplerV2 as Sampler

# SciPy minimizer routine
from scipy.optimize import minimize
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from qiskit_serverless import (
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
        estimator (EstimatorV2): Estimator primitive instance

    Returns:
        float: Energy estimate
    """
    pub = (ansatz, [hamiltonian], [params])
    result = estimator.run(pubs=[pub]).result()
    cost = result[0].data.evs[0]

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

    arguments = get_arguments()

    service = arguments.get("service")
    hamiltonian = arguments.get("operator")
    ansatz = arguments.get("ansatz")
    initial_point = arguments.get("initial_point")
    method = arguments.get("method", "COBYLA")
    backend = arguments.get("backend")

    if service:
        backend = service.least_busy(operational=True, simulator=False, min_num_qubits=127)
        session = Session(backend=backend)
    else:
        backend = AerSimulator()
    
    target = backend.target
    pm = generate_preset_pass_manager(target=target, optimization_level=3)
    ansatz_isa = pm.run(ansatz)
    operator = hamiltonian.apply_layout(ansatz_isa.layout)

    
    if service:
        estimator = Estimator(session=session)
        sampler = Sampler(session=session)
    else:
        estimator = Estimator(mode=backend)
        sampler = Sampler(mode=backend)

    estimator.options.default_shots = 10_000
    estimator.options.dynamical_decoupling.enable = True
    sampler.options.default_shots = 10_000
    sampler.options.dynamical_decoupling.enable = True

    initial_point = 2 * np.pi * np.random.rand(ansatz_isa.num_parameters)

    res = run_qaoa(ansatz_isa, estimator, operator, initial_point, method)

    # Assign solution parameters to ansatz
    qc = ansatz.assign_parameters(res.x)
    # Add measurements to our circuit
    qc.measure_all()
    qc_isa = pm.run(qc)

    result = sampler.run([qc_isa]).result()
    samp_dist = result[0].data.meas.get_counts()
    
    if service:
        session.close()

    save_result({"optimal_point": res.x.tolist(), "optimal_value": res.fun, "probabilitie":samp_dist})
