# Test environments

This repository's tests and development automation tasks are organized using [tox], a command-line CI frontend for Python projects.  tox is typically used during local development and is also invoked from this repository's GitHub Actions [workflows](/.github/workflows/).

tox can be installed by running `pip install tox`.

tox is organized around various "environments," each of which is described below.  To run all test environments, run `tox` without any arguments:

```sh
$ tox
```

Environments for this repository are configured in [`tox.ini`] as described below.

## Lint environment

The `lint` environment ensures that the code meets basic coding standards, including

- [_Black_] formatting style
- [mypy] type annotation checker, as configured by [`mypy.ini`]
- [pylint], as configured by [`.pylintrc`]

The _Black_ and mypy passes are applied also to [Jupyter] notebooks (via [nbqa]).

To run:

```sh
$ tox -elint
```

If the _Black_ check fails, the [_Black_ environment](#black-environment) can be invoked to easily reformat all files as necessary.

## _Black_ environment

The command `tox -eblack` will reformat all files in the repository according to _Black_ style.

## Test (py##) environments

The `py##` environments are the main test environments.  tox defines one for each version of Python.  For instance, the following command will run the tests on Python 3.8, Python 3.9, and Python 3.10:

```sh
$ tox -epy38,py39,py310
```

First, these environments execute all tests using [pytest], which supports its own simple style of tests, in addition to [unittest]-style tests and [doctests] located throughout the project's docstrings.

Second, these environments invoke [treon] to ensure that all Jupyter notebooks in the [`docs/`](/docs/) directory execute successfully.

## Coverage environment

The `coverage` environment uses [Coverage.py] to ensure that the fraction of code tested by pytest is above some threshold (80% at the time of writing).

To run:

```sh
$ tox -ecoverage
```


[tox]: https://github.com/tox-dev/tox
[`tox.ini`]: /tox.ini
[mypy]: https://mypy.readthedocs.io/en/stable/
[`mypy.ini`]: /mypy.ini
[treon]: https://github.com/ReviewNB/treon
[_Black_]: https://github.com/psf/black
[pylint]: https://github.com/PyCQA/pylint
[`.pylintrc`]: /.pylintrc
[nbqa]: https://github.com/nbQA-dev/nbQA
[Jupyter]: https://jupyter.org/
[doctests]: https://docs.python.org/3/library/doctest.html
[pytest]: https://docs.pytest.org/
[unittest]: https://docs.python.org/3/library/unittest.html
[Coverage.py]: https://coverage.readthedocs.io/
