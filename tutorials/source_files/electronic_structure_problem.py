"""Hardware efficient ansatze."""
from typing import List, Optional, Union, Any, Dict, Tuple

import numpy as np
from qiskit.algorithms.optimizers import COBYLA, Optimizer
from qiskit.circuit.library import TwoLocal as TLA
from qiskit.providers.ibmq import IBMQBackend
from qiskit.primitives import Estimator as QiskitEstimator
from qiskit_ibm_runtime import Estimator as RuntimeEstimator, Session, QiskitRuntimeService, Options
from qiskit_ibm_runtime.options import ExecutionOptions
from qiskit_nature.circuit.library import HartreeFock
from qiskit_nature.converters.second_quantization import QubitConverter
from qiskit_nature.drivers import Molecule
from qiskit_nature.drivers.second_quantization import PySCFDriver
from qiskit_nature.mappers.second_quantization import ParityMapper
from qiskit_nature.problems.second_quantization import ElectronicStructureProblem
from qiskit_nature.transformers.second_quantization.electronic import (
    ActiveSpaceTransformer,
)

from qiskit import QuantumCircuit
from qiskit.algorithms import MinimumEigensolver, VQEResult

from quantum_serverless import run_qiskit_remote, get


class EstimatorVQE(MinimumEigensolver):
    """EstimatorVQE."""

    def __init__(
        self,
        estimator: Union[QiskitEstimator, RuntimeEstimator],
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
        self._histories: List[Tuple[Any, Any]] = []

    def compute_minimum_eigenvalue(self, operator, aux_operators=None):
        # define objective
        def objective(parameters):
            e_job = self._estimator.run([self._circuit], [operator], [parameters])
            value = e_job.result().values[0]
            if self._callback:
                self._callback(value)
            print("value:", value)
            self._histories.append((parameters, value))
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

        return result, self._histories


@run_qiskit_remote(target={"cpu": 2})
def ground_state_solve(
    molecule: Molecule,
    initial_point: Union[List[float], np.ndarray],
    backend: str,
    optimization_level: int,
    resilience_level: int,
    shots: int,
    service: Optional[Union[QiskitRuntimeService, Dict[str, Any]]] = None,
    optimizer: Optional[Optimizer] = None,
    use_local_simulator: bool = False
):
    """Energy calculation using hardware efficient ansatz with VQE

    Args:
        molecule: molecule to use
        initial_point: initial point
        options: options for esimator
        service: runtime service
        optimizer: optimizer
        backend: name of backend
        use_local_simulator: run calculation using local Estimator simulator

    Returns:
        energy
    """
    # setup service
    if service and isinstance(service, dict):
        service = QiskitRuntimeService(**service)

    optimizer = optimizer or COBYLA(maxiter=500)

    transformer = ActiveSpaceTransformer(
        num_electrons=2, num_molecular_orbitals=3, active_orbitals=[1, 4, 5]
    )

    driver = PySCFDriver.from_molecule(molecule=molecule, basis="sto-3g")

    es_problem = ElectronicStructureProblem(driver, transformers=[transformer])

    qubit_converter = QubitConverter(
        mapper=ParityMapper(),
        two_qubit_reduction=True,
        z2symmetry_reduction=None,
    )

    operator = qubit_converter.convert(
        es_problem.second_q_ops()[0],
        num_particles=es_problem.num_particles,
    )

    particle_number = es_problem.grouped_property_transformed.get_property(
        "ParticleNumber"
    )
    hf_full = HartreeFock(
        num_spin_orbitals=particle_number.num_spin_orbitals,
        num_particles=particle_number.num_particles,
        qubit_converter=qubit_converter,
    )

    electronic_energy = es_problem.grouped_property_transformed.get_property(
        "ElectronicEnergy"
    )
    e_shift = electronic_energy.nuclear_repulsion_energy + np.real(
        electronic_energy._shift["ActiveSpaceTransformer"]
    )

    ansatz = TLA(
        rotation_blocks=["ry"],
        entanglement_blocks="cx",
        entanglement="linear",
        initial_state=hf_full,
        skip_final_rotation_layer=True,
        reps=1,
    )

    print("optimizer", optimizer)
    ansatz.num_qubits = operator.num_qubits
    print(f"molecule: {molecule.geometry}, shift {e_shift}")
    with Session(service=service, backend=backend) as session:
        if use_local_simulator is True:
            estimator = QiskitEstimator()
        else:
            options = Options()
            options.optimization_level = optimization_level
            options.resilience_level = resilience_level
            options.execution.shots = shots
            estimator = RuntimeEstimator(session=session, options=options)

        vqe = EstimatorVQE(
            estimator=estimator,
            circuit=ansatz,
            optimizer=optimizer,
            init_point=initial_point,
        )

        vqe_result, histories = vqe.compute_minimum_eigenvalue(operator)

    return vqe_result.optimal_value, e_shift, histories


def electronic_structure_problem(
    molecules: List[Molecule],
    initial_points: Optional[List[List[float]]] = None,
    service: Optional[QiskitRuntimeService] = None,
    backends: Optional[List[IBMQBackend]] = None,
    optimization_level: int = 1,
    resilience_level: int = 0,
    shots: int = 4000,
    optimizer: Optional[Optimizer] = None,
    use_local_simulator: bool = False
):
    """Parallel VQE energy calculation using hardware efficient ansatz

    Args:
        molecules: list of molecules to run
        initial_points: optional list of initial points
        service: runtime service
        backends: list of backends to run against
        resilience_level: resilience level
        optimization_level: optimization level
        shots: number of shots
        optimizer: optimizer
        use_local_simulator: run calculation using local Estimator simulator

    Returns:
        list of VQE energies
    """
    service = service or QiskitRuntimeService()
    initial_points = initial_points or [None] * len(molecules)
    backends = backends or [None] * len(molecules)

    function_references = [
        ground_state_solve(
            molecule=molecule,
            initial_point=initial_point,
            backend=backend.name if backend else "ibmq_qasm_simulator",
            optimization_level=optimization_level,
            resilience_level=resilience_level,
            shots=shots,
            service=service.active_account(),
            optimizer=optimizer,
            use_local_simulator=use_local_simulator,
        )
        for molecule, initial_point, backend in zip(molecules, initial_points, backends)
    ]

    return get(function_references)
