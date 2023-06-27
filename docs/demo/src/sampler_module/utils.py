from qiskit.providers.fake_provider import FakeLimaV2


backend_mapping = {
    "lima": FakeLimaV2
}


def create_backend(backend_string: str):
    return backend_mapping.get(backend_string, FakeLimaV2)()
