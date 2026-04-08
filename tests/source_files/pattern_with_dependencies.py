# source_files/program_4.py

from qiskit_serverless import save_result

from mergedeep import merge

# Test mergedeep functionality
dict1 = {"a": 1, "b": {"c": 2}}
dict2 = {"b": {"d": 3}, "e": 4}

result = merge(dict1, dict2)

print(result)
save_result({"merged": result})
