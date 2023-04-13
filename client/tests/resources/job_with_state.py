from quantum_serverless import QuantumServerless, run_qiskit_remote, get

from quantum_serverless.core.state import RedisStateHandler

state_handler = RedisStateHandler("redis", 6379)

serverless = QuantumServerless()


@run_qiskit_remote(state=state_handler)
def func_with_state(state: RedisStateHandler, seed: int):
    state.set("in_job", {"k": seed})
    return seed


@run_qiskit_remote(state=state_handler)
def other_func_with_state(state: RedisStateHandler, seed: int):
    state.set("in_other_job", {"other_k": seed})
    return get(func_with_state(seed))


with serverless:
    result = get(other_func_with_state(42))

print(result)
