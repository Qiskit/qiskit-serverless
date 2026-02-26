import os
import tarfile
from qiskit_serverless import save_result

with open("./my_file.txt", "w") as f:
    f.write("Hello!")

data_path = os.environ.get("DATA_PATH")
with tarfile.open(f"{data_path}/my_file.tar", "w:gz") as tar:
    tar.add("./my_file.txt")

save_result({"Message": "my_file.txt archived into my_file.tar"})
