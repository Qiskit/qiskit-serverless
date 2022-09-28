"""Primitives."""
from __future__ import annotations

from typing import Optional, Union, Dict, Sequence, Any, Tuple, List
from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.opflow import PauliSumOp
from qiskit.quantum_info.operators.base_operator import BaseOperator
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    Estimator,
    Session,
    RuntimeOptions,
    Options,
    EstimatorResult,
)
from quantum_serverless import run_qiskit_remote, get
from .utils import SessionParameters


# pylint: disable=protected-access
@dataclass
class EstimatorParameters:
    """EstimatorParameters."""

    circuits: Union[QuantumCircuit, Sequence[QuantumCircuit]]
    observables: Sequence[BaseOperator | PauliSumOp]
    kwargs: Any
    parameter_values: Optional[Union[Sequence[float], Sequence[Sequence[float]]]] = None
    parameters: Sequence[Sequence[Parameter]] | None = None


@run_qiskit_remote()
def estimate_remotely(
    service_parameterss: SessionParameters,
    estimator_parameters: EstimatorParameters,
    options: Optional[Union[Dict, RuntimeOptions, Options]] = None,
):
    """

    Args:
        service_parameterss:
        estimator_parameters:
        options:

    Returns:

    """
    service = (
        QiskitRuntimeService(**service_parameterss.active_account)
        if service_parameterss.active_account is not None
        else None
    )
    session = Session(service=service, max_time=service_parameterss.max_time)
    if service_parameterss.session_id:
        session._session_id = service_parameterss.session_id

    estimator = Estimator(session=session, options=options)
    job = estimator.run(
        circuits=estimator_parameters.circuits,
        observables=estimator_parameters.observables,
        parameter_values=estimator_parameters.parameter_values,
        parameters=estimator_parameters.parameters,
        **estimator_parameters.kwargs,
    )
    return job.result()


class ParallelEstimator(Estimator):
    """ParallelEstimator."""

    def __init__(
        self,
        session: Optional[Session] = None,
        options: Optional[Union[Dict, RuntimeOptions, Options]] = None,
    ):
        """ParallelEstimator class.

        Args:
            session: session object
            options: additional options
        """
        super().__init__(session=session, options=options)
        self._workloads: List[Tuple[SessionParameters, EstimatorParameters]] = []

    def add(
        self,
        circuits: Union[QuantumCircuit, Sequence[QuantumCircuit]],
        observables: Sequence[BaseOperator | PauliSumOp],
        parameter_values: Optional[
            Union[Sequence[float], Sequence[Sequence[float]]]
        ] = None,
        parameters: Sequence[Sequence[Parameter]] | None = None,
        **kwargs: Any,
    ):
        """

        Args:
            circuits:
            observables:
            parameter_values:
            parameters:
            **kwargs:

        Returns:

        """
        active_account = None
        if self.session is not None and self.session.service is not None:
            active_account = self.session.service.active_account()

        session_id = None
        if self.session is not None:
            session_id = self.session.session_id

        max_time = None
        if self.session is not None:
            max_time = self.session._max_time

        session_parameters = SessionParameters(active_account, session_id, max_time)
        estimator_parameters = EstimatorParameters(
            circuits=circuits,
            observables=observables,
            kwargs=kwargs,
            parameter_values=parameter_values,
            parameters=parameters,
        )
        self._workloads.append((session_parameters, estimator_parameters))

    def run_all(self) -> List[EstimatorResult]:
        """Run all added estimator jobs.

        Returns:
            list of estimator results
        """
        if len(self._workloads) == 0:
            return []

        return get(
            [
                estimate_remotely(
                    service_parameterss=service_parameterss,
                    estimator_parameters=estimator_parameters,
                    options=self.options,
                )
                for (service_parameterss, estimator_parameters) in self._workloads
            ]
        )
