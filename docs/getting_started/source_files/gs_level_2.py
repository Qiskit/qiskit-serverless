from quantum_serverless import get_arguments

from qiskit_nature.units import DistanceUnit
from qiskit_nature.second_q.drivers import PySCFDriver
from qiskit_nature.second_q.mappers import QubitConverter
from qiskit_nature.second_q.mappers import ParityMapper
from qiskit_nature.second_q.properties import ParticleNumber
from qiskit_nature.second_q.transformers import ActiveSpaceTransformer
from qiskit.algorithms.minimum_eigensolvers import NumPyMinimumEigensolver
from qiskit_nature.second_q.algorithms.ground_state_solvers import GroundStateEigensolver
from qiskit.circuit.library import EfficientSU2
import numpy as np
from qiskit.utils import algorithm_globals
from qiskit.algorithms.optimizers import SPSA
from qiskit.algorithms.minimum_eigensolvers import VQE
from qiskit.primitives import Estimator


def run(bond_distance: float = 2.5):
    driver = PySCFDriver(
        atom=f"Li 0 0 0; H 0 0 {bond_distance}",
        basis="sto3g",
        charge=0,
        spin=0,
        unit=DistanceUnit.ANGSTROM,
    )
    problem = driver.run()

    active_space_trafo = ActiveSpaceTransformer(
        num_electrons=problem.num_particles, num_spatial_orbitals=3
    )
    problem = active_space_trafo.transform(problem)
    qubit_converter = QubitConverter(ParityMapper(), two_qubit_reduction=True)

    ansatz = EfficientSU2(num_qubits=4, reps=1, entanglement="linear", insert_barriers=True)

    np.random.seed(5)
    algorithm_globals.random_seed = 5


    optimizer = SPSA(maxiter=100)
    initial_point = np.random.random(ansatz.num_parameters)

    estimator = Estimator()
    local_vqe = VQE(
        estimator,
        ansatz,
        optimizer,
        initial_point=initial_point,
    )

    local_vqe_groundstate_solver = GroundStateEigensolver(qubit_converter, local_vqe)
    local_vqe_result = local_vqe_groundstate_solver.solve(problem)

    print(local_vqe_result)


arguments = get_arguments()
bond_length = arguments.get("bond_length", 2.55)
print(f"Running for bond length {bond_length}.")
run(bond_length)
