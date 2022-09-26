"""VQE."""
import numpy as np

from qiskit import QuantumCircuit
from qiskit.algorithms import MinimumEigensolver, VQEResult
from qiskit.algorithms.optimizers import Optimizer

from qiskit_ibm_runtime import Estimator


class EstimatorVQE(MinimumEigensolver):
    """EstimatorVQE."""

    def __init__(
        self,
        estimator: Estimator,
        circuit: QuantumCircuit,
        optimizer: Optimizer,
        callback=None,
    ):
        """EstimatorVQE - VQE implementation using Qiskit Runtime Estimator primitive

        Example:
            >>> with Session(service=service) as session:
            >>>     estimator = Estimator(session=session, options=options)
            >>>     custom_vqe = EstimatorVQE(estimator, circuit, optimizer)
            >>>     result = custom_vqe.compute_minimum_eigenvalue(operator)

        Args:
            estimator: Qiskit Runtime Estimator
            circuit: ansatz cirucit
            optimizer: optimizer
            callback: callback function
        """
        self._estimator = estimator
        self._circuit = circuit
        self._optimizer = optimizer
        self._callback = callback

    def compute_minimum_eigenvalue(self, operator, aux_operators=None):
        # define objective
        def objective(parameters):
            e_job = self._estimator.run([self._circuit], [operator], [parameters])
            value = e_job.result().values[0]
            if self._callback:
                self._callback(value)
            return value

        # run optimization
        init_params = np.random.rand(self._circuit.num_parameters)
        res = self._optimizer.minimize(objective, x0=init_params)

        # populate results
        result = VQEResult()
        result.cost_function_evals = res.nfev
        result.eigenvalue = res.fun
        result.optimal_parameters = res.x
        return result
