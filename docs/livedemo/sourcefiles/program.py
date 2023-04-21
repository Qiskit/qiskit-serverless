from quantum_serverless import QuantumServerless, save_result, get_arguments, get

from tabulate import tabulate

from mymodule.tasks import ditribute_sample, distributed_transpile


serverless = QuantumServerless()

arguments = get_arguments()
circuit = arguments.get("circuit")


with serverless.context():
    results = get([
        distributed_transpile(circuit, seed)
        for seed in range(1, 10)
    ])
    
    table = [[seed, depth] for (c, depth), seed in zip(results, range(1, 10))]
    
    print("All results")
    print("=======")
    print(tabulate(table, headers=["seed", "depth"]))
    
    result = min(results, key=lambda x: x[1])
    distributions = get(ditribute_sample(result[0]))

    print("========")
    print("Depth:", result[1])
    print("Distribution:", distributions)
    
    save_result({
        "table": table,
        "best_distribution": distributions
    })
