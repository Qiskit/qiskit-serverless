"""Sampler."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union, Dict, Sequence, Any, Tuple, List

from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    Sampler,
    Session,
    RuntimeOptions,
    Options,
    SamplerResult,
)

from quantum_serverless import run_qiskit_remote, get
from .utils import SessionParameters


# pylint: disable=protected-access,duplicate-code
@dataclass
class SamplerParameters:
    """SamplerParameters."""

    circuits: Union[QuantumCircuit, Sequence[QuantumCircuit]]
    kwargs: Any
    parameter_values: Optional[Union[Sequence[float], Sequence[Sequence[float]]]] = None
    parameters: Sequence[Sequence[Parameter]] | None = None


@run_qiskit_remote()
def sample_remotely(
    service_parameterss: SessionParameters,
    sampler_parameters: SamplerParameters,
    options: Optional[Union[Dict, RuntimeOptions, Options]] = None,
):
    """

    Args:
        service_parameterss:
        sampler_parameters:
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

    sampler = Sampler(session=session, options=options)
    job = sampler.run(
        circuits=sampler_parameters.circuits,
        parameter_values=sampler_parameters.parameter_values,
        parameters=sampler_parameters.parameters,
        **sampler_parameters.kwargs,
    )
    return job.result()


class ParallelSampler(Sampler):
    """ParallelSampler."""

    def __init__(
        self,
        session: Optional[Session] = None,
        options: Optional[Union[Dict, RuntimeOptions, Options]] = None,
    ):
        """ParallelSampler class.

        Args:
            session:
            options:
        """
        self._workloads: List[Tuple[SessionParameters, SamplerParameters]] = []
        super().__init__(session=session, options=options)

    def add(
        self,
        circuits: Union[QuantumCircuit, Sequence[QuantumCircuit]],
        parameter_values: Optional[
            Union[Sequence[float], Sequence[Sequence[float]]]
        ] = None,
        parameters: Sequence[Sequence[Parameter]] | None = None,
        **kwargs: Any,
    ):
        """

        Args:
            circuits:
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
        sampler_parameters = SamplerParameters(
            circuits=circuits,
            kwargs=kwargs,
            parameter_values=parameter_values,
            parameters=parameters,
        )
        self._workloads.append((session_parameters, sampler_parameters))

    def run_all(self) -> List[SamplerResult]:
        """Run all added estimator jobs.

        Returns:
            list of estimator results
        """
        if len(self._workloads) == 0:
            return []

        return get(
            [
                sample_remotely(
                    service_parameterss=service_parameterss,
                    sampler_parameters=sampler_parameters,
                    options=self.options,
                )
                for (service_parameterss, sampler_parameters) in self._workloads
            ]
        )
