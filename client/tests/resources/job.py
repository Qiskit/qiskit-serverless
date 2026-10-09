import ray


@ray.remote
def ultimate():
    return 42


result = ray.get([ultimate.remote() for _ in range(10)])

print(result)
