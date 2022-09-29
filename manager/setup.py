import os
from setuptools import setup

requires = (
    "flask",
    "flask-sqlalchemy",
    "requests>=0.13.6",
    "python-dateutil>=1.5",
    "twilio",
    "selenium",
)


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


with open("requirements.txt") as f:
    required = f.read().splitlines()


setup(
    name="Manager",
    version="0.0.1",
    author="IBM",
    description=("Quantum Serverless Manager"),
    keywords="quantum serverless manager",
    packages=["manager"],
    install_requires=required,
    long_description=read("README.md"),
)
