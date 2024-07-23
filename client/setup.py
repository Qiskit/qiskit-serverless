"""Setup file for Qiskit Serverless client."""
import os
import setuptools

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    install_requires = f.read().splitlines()

version_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "qiskit_serverless", "VERSION.txt")
)

with open(version_path, "r") as fd:
    version = fd.read().rstrip()

setuptools.setup(
    name="qiskit_serverless",
    description="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords="qiskit serverless quantum computing",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    python_requires=">=3.11",
    version=version,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: MacOS",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Physics",
    ],
)
