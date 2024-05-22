# source_files/program_4.py

from qiskit_serverless import save_result

# from qiskit.primitives import Sampler
# from qiskit_experiments.library import StandardRB
import pendulum


# arguments = get_arguments()

# circuit = arguments.get("circuit")

# rb = StandardRB(physical_qubits=(1,), lengths=list(range(1, 300, 30)), seed=42)
# composed = circuit.compose(rb.circuits()[0])

# sampler = Sampler()

# quasi_dists = sampler.run(composed).result().quasi_dists

# print(f"Quasi distribution: {quasi_dists[0]}")

# # saving results of a program
# save_result({"quasi_dists": quasi_dists[0]})

dt_toronto = pendulum.datetime(2012, 1, 1, tz='America/Toronto')
dt_vancouver = pendulum.datetime(2012, 1, 1, tz='America/Vancouver')

diff = dt_vancouver.diff(dt_toronto).in_hours() 

print(diff)
save_result({"hours": diff})
