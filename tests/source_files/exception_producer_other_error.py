# This is not a custom function example.
# This is a test code that is inyected into a main.tmpl
# simulating provider functions execution.
class Runner:
    def run(self, arguments):
        print("VALUE ERROR RAISING")
        raise ValueError("This is not a ServerlessError")
