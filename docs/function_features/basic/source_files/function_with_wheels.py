"""Function entrypoint that installs user-uploaded wheels, for the BYO-wheels guide."""

from qiskit_serverless import install_uploaded_wheels, save_result

# Install any wheels uploaded with client.add_wheels() and make them importable.
# Call this before importing the uploaded packages.
install_uploaded_wheels()

import mypkg  # noqa: E402  (importable only after install_uploaded_wheels())

save_result({"mypkg_version": mypkg.__version__})
