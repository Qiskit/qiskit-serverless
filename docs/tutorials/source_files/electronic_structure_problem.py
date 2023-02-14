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
from qiskit.algorithms.minimum_eigensolvers import VQE
from qiskit_nature.drivers import Molecule
from qiskit.algorithms.optimizers import SPSA

from quantum_serverless import run_qiskit_remote, get, QuantumServerless
from quantum_serverless.core import RedisStateHandler


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
    if service and isinstance(service, dict) and not use_local_simulator:
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
        es_problem.second_q_ops()["ElectronicEnergy"],
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

    ansatz.num_qubits = operator.num_qubits

    if use_local_simulator is True:
        estimator = QiskitEstimator()

        vqe = VQE(
            estimator=estimator,
            ansatz=ansatz,
            optimizer=optimizer,
            initial_point=initial_point,
        )

        vqe_result = vqe.compute_minimum_eigenvalue(operator)
    else:
        with Session(service=service, backend=backend) as session:
            options = Options()
            options.optimization_level = optimization_level
            options.resilience_level = resilience_level
            options.execution.shots = shots
            estimator = RuntimeEstimator(session=session, options=options)

            vqe = VQE(
                estimator=estimator,
                ansatz=ansatz,
                optimizer=optimizer,
                initial_point=initial_point,
            )

            vqe_result = vqe.compute_minimum_eigenvalue(operator)

    return vqe_result.optimal_value, e_shift


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
    service_account: Dict[str, Any] = {}
    if service is not None and isinstance(service, QiskitRuntimeService):
        service_account = service.active_account()
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
            service=service_account,
            optimizer=optimizer,
            use_local_simulator=use_local_simulator,
        )
        for molecule, initial_point, backend in zip(molecules, initial_points, backends)
    ]

    return get(function_references)


if __name__ == '__main__':
    serverless = QuantumServerless()
    state_handler = RedisStateHandler("redis", 6379)

    USE_RUNTIME = False

    service = None
    backends = None
    if USE_RUNTIME:
        service = QiskitRuntimeService()
        names = ["ibmq_qasm_simulator", "ibmq_qasm_simulator", "ibmq_qasm_simulator"]
        backends = [service.backend(name) for name in names]

    with serverless.context():
        energies = electronic_structure_problem(
            molecules=[
                Molecule(geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 1.0])], charge=0, multiplicity=1),
                Molecule(geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 1.5])], charge=0, multiplicity=1),
                Molecule(geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 2.0])], charge=0, multiplicity=1),
            ],
            initial_points=[
                [0.1, 0.1, 0.1, 0.1],
                [0.01, 0.01, 0.01, 0.01],
                [0.001, 0.001, 0.001, 0.001],
            ],
            service=service,
            backends=backends,
            optimization_level=1,
            resilience_level=1,
            shots=4000,
            optimizer=SPSA(),
            use_local_simulator=not USE_RUNTIME
        )

    print("LiH experiment results:")
    print("Energies: ", [e[0] for e in energies])
    print("Shifts: ", [e[1] for e in energies])
    print("Energy + shift: ", [e[0] + e[1] for e in energies])

    state_handler.set("results", {
        "energies": [e[0] for e in energies],
        "shifts": [e[1] for e in energies]
    })
