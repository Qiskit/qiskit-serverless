# QuantumServerless Beginner's Guide

## About the Project
Today a lot of experiments are happening on a local machines or on manually allocated remote resources. This approach is not scalable and we need to give users tools to run hybrid workloads without worrying about allocating and managing underlying infrastructure. Moreover, the majority of code written today is not structured in a way to leverage parallel hybrid compute.

This project is aimed to give users a simple way of writing parallel hybrid code and scale it up on available hardware.

The project is structured as a monorepo, so it has 3 separate sub-modules:
- [client](../client)
- [manager](../manager)
- [infrastructure](../infrastructure)

## Installation

Refer to [installation guide](../INSTALL.md).

## Usage

```python
from quantum_serverless import QuantumServerless, run_qiskit_remote, get

# 1. let's annotate out function to convert it 
# to function that can be executed remotely
# using `run_qiskit_remote` decorator
@run_qiskit_remote()
def my_qiskit_function():
    # Doing compute things here!
    return "Computed result"


# 2. Next let's create out serverless object to control 
# where our remote function will be executed
serverless = QuantumServerless()

# 2.1 (optional) check available providers
print(f"Available providers: {serverless.providers()}")

# 3. create serverless context 
with serverless:
    # 4. run our function and get back reference to it
    # as now our function it remote one
    function_reference = my_qiskit_function()
    # 4.1 or we can run N of them in parallel
    N = 4
    function_references = [my_qiskit_function() for _ in range(N)]
    
    # 5. to get results back from reference 
    # we need to call `get` on function reference
    print(get(function_reference))
    print(get(function_references))
```

For more examples refer to [guides](./guides) and [tutorials](./tutorials).
