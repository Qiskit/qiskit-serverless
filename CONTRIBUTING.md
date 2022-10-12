# Contributing

**We appreciate all kinds of help, so thank you!**

## Contributing to QuantumServerless

Specific details for contributing to this project are outlined below.

### Reporting Bugs and Requesting Features

Users are encouraged to use GitHub Issues for reporting issues and requesting features.

### Project Code Style

Code in this repository should conform to PEP8 standards. Style/lint checks are run to validate this. Line length must be limited to no more than 88 characters.

### Pull Request Checklist

When submitting a pull request and you feel it is ready for review,
please ensure that:

1. The code follows the _code style_ of this project and successfully
   passes the _unit tests_. This project uses [Pylint](https://www.pylint.org) and
   [PEP8](https://www.python.org/dev/peps/pep-0008) style guidelines.

   You can run
   ```shell script
   tox -elint
   ```
   from [`client/`, `manager/`] folders for lint conformance checks.
