"""VQE."""
from typing import Optional

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
        init_point: Optional[np.ndarray] = None,
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
            init_point: optional initial point for optimization
        """
        self._estimator = estimator
        self._circuit = circuit
        self._optimizer = optimizer
        self._callback = callback
        self._init_point = init_point

    def compute_minimum_eigenvalue(self, operator, aux_operators=None):
        # define objective
        def objective(parameters):
            if isinstance(self._estimator, Estimator):
                e_job = self._estimator.run([self._circuit], [operator], [parameters])
                value = e_job.result().values[0]
            else:
                e_job = self._estimator([self._circuit], [operator], [parameters])
                value = e_job.values[0]
            if self._callback:
                self._callback(value)
            return value

        # run optimization
        init_params = (
            np.random.rand(self._circuit.num_parameters)
            if self._init_point is None
            else self._init_point
        )
        res = self._optimizer.minimize(objective, x0=init_params)

        result = VQEResult()
        result.optimal_point = res.x
        result.optimal_parameters = dict(zip(self._circuit.parameters, res.x))
        result.optimal_value = res.fun
        result.cost_function_evals = res.nfev
        result.optimizer_time = res
        result.eigenvalue = res.fun + 0j

        return result
