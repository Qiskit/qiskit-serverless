from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler as Sampler


def custom_function(arguments):
    import pendulum  # type: ignore

    dt_toronto = pendulum.datetime(2012, 1, 1, tz="America/Toronto")
    dt_vancouver = pendulum.datetime(2012, 1, 1, tz="America/Vancouver")

    diff = dt_vancouver.diff(dt_toronto).in_hours()

    print(diff)

    # all print statement will be available in job logs
    print("Running function...")
    message = arguments.get("message")
    print(message)

    # creating circuit
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()

    # running Sampler primitive
    sampler = Sampler()
    quasi_dists = sampler.run([(circuit)]).result()[0].data.meas.get_counts()

    print("Completed running pattern.")
    return quasi_dists


class Runner:
    def run(self, arguments: dict) -> dict:
        return custom_function(arguments)
