"""Hardware efficient ansatze."""
import random
from typing import List, Optional, Union, Any, Dict

import numpy as np
from qiskit.algorithms.optimizers import COBYLA
from qiskit.circuit.library import TwoLocal as TLA
from qiskit.primitives import Estimator as QiskitEstimator
from qiskit.providers.ibmq import IBMQBackend
from qiskit_ibm_runtime import Estimator, Session, QiskitRuntimeService, Options
from qiskit_nature.circuit.library import HartreeFock
from qiskit_nature.converters.second_quantization import QubitConverter
from qiskit_nature.drivers import Molecule
from qiskit_nature.drivers.second_quantization import PySCFDriver
from qiskit_nature.mappers.second_quantization import ParityMapper
from qiskit_nature.problems.second_quantization import ElectronicStructureProblem
from qiskit_nature.transformers.second_quantization.electronic import (
    ActiveSpaceTransformer,
)

from quantum_serverless import run_qiskit_remote, get
from quantum_serverless.library import EstimatorVQE


@run_qiskit_remote(target={"cpu": 2})
def hardware_efficient_ansatz(
    molecule: Molecule,
    initial_point: Union[List[float], np.ndarray],
    options: Optional[Options] = None,
    service: Optional[Union[QiskitRuntimeService, Dict[str, Any]]] = None,
):
    """Energy calculation using hardware efficient ansatz with VQE

    Args:
        molecule: molecule to use
        initial_point: initial point
        options: options for esimator
        service: runtime service

    Returns:
        energy
    """
    # setup service
    if service and isinstance(service, dict):
        service = QiskitRuntimeService(**service)

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

    optimizer = COBYLA(maxiter=500)
    ansatz.num_qubits = operator.num_qubits

    with Session(service=service) as session:
        estimator = QiskitEstimator([ansatz], [operator])
        estimator = Estimator(session=session, options=options)

        vqe = EstimatorVQE(
            estimator=estimator,
            circuit=ansatz,
            optimizer=optimizer,
            init_point=initial_point,
        )

        vqe_result = vqe.compute_minimum_eigenvalue(operator)

    return vqe_result.optimal_value + e_shift


def efficient_ansatz_vqe_sweep(
    molecules: List[Molecule],
    initial_points: Optional[List[List[float]]] = None,
    service: Optional[QiskitRuntimeService] = None,
    backends: Optional[List[IBMQBackend]] = None,
):
    """Parallel VQE energy calculation using hardware efficient ansatz

    Args:
        molecules: list of molecules to run
        initial_points: optional list of initial points
        service: runtime service
        backends: list of backends to run against

    Returns:
        list of VQE energies
    """
    service = service or QiskitRuntimeService()

    optimization_level = 1
    resilience_level = 0
    options = [
        Options(
            optimization_level=optimization_level,
            resilience_level=resilience_level,
            backend=random.choice(backends).name()
            if backends
            else "ibmq_qasm_simulator",
        )
        for _ in range(len(molecules))
    ]

    initial_points = initial_points or [None] * len(molecules)

    function_references = [
        hardware_efficient_ansatz(
            molecule=molecule,
            initial_point=initial_point,
            options=opt,
            service=service.active_account(),
        )
        for molecule, initial_point, opt in zip(molecules, initial_points, options)
    ]

    return get(function_references)
