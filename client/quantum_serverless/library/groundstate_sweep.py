"""GroundState sweep."""

import random
from dataclasses import dataclass
from typing import List, Union, Optional, Any, Dict

from qiskit import Aer, QuantumCircuit
from qiskit.providers import Backend
from qiskit.algorithms import VQE
from qiskit.utils import QuantumInstance
from qiskit_nature.algorithms import GroundStateEigensolver
from qiskit_nature.algorithms import VQEUCCFactory
from qiskit_nature.converters.second_quantization import QubitConverter
from qiskit_nature.drivers import Molecule
from qiskit_nature.drivers.second_quantization import (
    ElectronicStructureDriverType,
    ElectronicStructureMoleculeDriver,
)
from qiskit_nature.mappers.second_quantization import JordanWignerMapper
from qiskit_nature.problems.second_quantization import ElectronicStructureProblem
from qiskit_nature.results import EigenstateResult

from quantum_serverless.core.decorators import run_qiskit_remote, get
from quantum_serverless.exception import QuantumServerlessException


@dataclass
class SweepResult:
    """SweepResult."""

    result: EigenstateResult
    parameters: Dict[str, Any]


@run_qiskit_remote(target={"cpu": 2})
def ground_state_solve(
    backend: Backend,
    molecule: Molecule,
    ansatz: Optional[QuantumCircuit] = None,
):
    """Run of ground state solver on given arguments.

    Args:
        backend: backend
        molecule: molecule
        ansatz: ansatz for VQE

    Returns:
        solver result
    """
    driver = ElectronicStructureMoleculeDriver(
        molecule, basis="sto3g", driver_type=ElectronicStructureDriverType.PYSCF
    )

    es_problem = ElectronicStructureProblem(driver)
    qubit_converter = QubitConverter(JordanWignerMapper())

    quantum_instance = QuantumInstance(backend=backend)
    vqe_solver = VQE(quantum_instance=quantum_instance, ansatz=ansatz)

    calc = GroundStateEigensolver(qubit_converter, vqe_solver)
    return calc.solve(es_problem)


def groundstate_solver_parallel_sweep(
    molecules: Union[List[Molecule], List[List[str]]],
    backends: Optional[List[Backend]] = None,
    geometries: Optional[List[List[List[float]]]] = None,
    ansatz: Optional[List[QuantumCircuit]] = None,
    n_geometries: Optional[int] = None
):
    """Groundstate solver parallel sweep.
    Number of parallel runs will be product of parameter values passed.

    Example:
        >>> sweep_results: List[SweepResult] = groundstate_solver_parallel_sweep(
        >>>    molecules=[["H", "H"]]
        >>> )

    Args:
        n_geometries: number of geometries to generate is none was given
        molecules: list of molecules
        backends: list of backends to run
        geometries: geometries of molecules if molecules themselves where passed as strings
        ansatz: ansatz for VQE

    Returns:
        list of sweep results (solver result + parameters)
    """
    if not isinstance(molecules, list):
        raise QuantumServerlessException("Molecules argument must be a list.")

    n_geometries = n_geometries or 1
    ansatz = ansatz or []
    backends = backends or [Aer.get_backend("aer_simulator_statevector")]

    if isinstance(molecules[0], list):
        # use string list
        if geometries is not None:
            updated_molecules = []
            for geom, molecule in zip(geometries, molecules):
                geometry = list(zip(molecule, geom))
                updated_molecules.append(Molecule(geometry=geometry))
        else:
            # generate geometries
            updated_molecules = []
            for molecule in molecules:
                for _ in range(n_geometries):
                    geometry = [
                        (
                            atom,
                            [
                                random.uniform(0.1, 0.5),
                                random.uniform(0.1, 0.5),
                                random.uniform(0.1, 0.5),
                            ],
                        )
                        for atom in molecule
                    ]
                    updated_molecules.append(Molecule(geometry=geometry))

        molecules: List[Molecule] = updated_molecules

    trials = []

    for molecule in molecules:
        if len(ansatz) > 0:
            for ans in ansatz:
                trials.append({"molecule": molecule, "ansatz": ans})
        else:
            trials.append({"molecule": molecule})

    updated_trials = [
        {**trial, **{"backend": random.choice(backends)}} for trial in trials
    ]

    tasks = []
    for trial in updated_trials:
        tasks.append(ground_state_solve(**trial))

    results = get(tasks)

    return [
        SweepResult(result, parameters)
        for result, parameters in zip(results, updated_trials)
    ]
