import os
import tarfile
from qiskit_serverless import save_result

with tarfile.open("/data/my_file.tar", "r:gz") as tar:
    with tar.extractfile("./my_file.txt") as f:
        text = f.read().decode("utf-8")

print(text)
save_result({"Message": text})
