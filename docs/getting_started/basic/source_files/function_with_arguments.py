from qiskit_serverless import get_arguments, save_result
from qiskit.primitives import StatevectorSampler as Sampler

# get all arguments passed to this function
arguments = get_arguments()

# get specific argument that we are interested in
circuit = arguments.get("circuit")

sampler = Sampler()

quasi_dists = sampler.run([(circuit)]).result()[0].data.meas.get_counts()

print(f"Quasi distribution: {quasi_dists}")

# saving results of the execution
save_result({"quasi_dists": quasi_dists})
