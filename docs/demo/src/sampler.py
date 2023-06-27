from quantum_serverless import get, distribute_task, save_result, get_arguments, QuantumServerless

from qiskit import transpile

from sampler_module.utils import create_backend


@distribute_task()
def distributed_transpile(circuit, backend):
    return transpile(circuit, backend)

arguments = get_arguments()
circuits = arguments.get("circuits", [])
backend = create_backend(
    arguments.get("backend", "lima")
)

with QuantumServerless().context():
    # pipeline
    # 1. transpile
    # 2. run
    # 3. quasi distr
    
    # transpile
    transliped_references = [
        distributed_transpile(circuit, backend)
        for circuit in circuits
    ]
    
    # mitigation
    # TODO: implement if needed
    
    # run
    backend_results = backend.run(get(transliped_references)).result().results
    
    # quasi distr
    results = []
    for r in backend_results:
        results.append(
            {key: value/r.shots for key, value in r.data.counts.items()}
        )
    
    # save results
    save_result(results)
