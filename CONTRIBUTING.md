# Contributing

Regardless if you are part of the core team or an external contributor, welcome and thank you for contributing to Qiskit Serverless!

In Qiskit Serverless, we aim at creating an excellent work-space where all of us can feel welcomed, useful, respected and valued. If you are thinking to contribute to this project, you agree to abide by our [code of conduct](CODE_OF_CONDUCT.md) which we strongly recommend you read before continuing.

Following these guidelines communicates you value the time and effort of the core contributors and maintainers of this site and so, thank you!


## Table of contents

- [Start contributing](#start-contributing)
- [Before you start](#before-you-start)
- [Opening issues](#opening-issues)
- [Contributing code](#contributing-code)
  - [Tools](#tools)
    - [For non-Linux users](#for-non-linux-users)
  - [Deciding what to work on](#deciding-what-to-work-on)
  - [Clone the repo](#clone-the-repo)
  - [Development environment](#development-environment)
  - [Assigning yourself](#assigning-yourself)
  - [Working on an issue](#working-on-an-issue)
  - [Adding tests](#adding-tests)
  - [Pull requests](#pull-requests)
  - [Live previews](#live-previews)
  - [Code review](#code-review)
  - [Merging](#merging)
- [Code style](#code-style)
  - [Solving linting issues](#solving-linting-issues)


## Start contributing

This repository is for developing and maintaining the Qiskit Serverless project.

There are many ways of contributing: from catching a typo to coming up with a way
of improving performance or accessibility; you can open an issue, or you can prepare
a patch. In any case, read the contribution guidelines for opening new issues and
submitting pull requests.


## Before you start

Contributing to Qiskit Serverless assumes you have some level
of [Git](https://git-scm.com) knowledge. For external contributors, a basic understanding
of repositories, remotes, branches and commits is needed. For core contributors, you
should know about resolving conflicts and rebasing too.

There are tons of useful resources about Git [out there](https://try.github.io/).


## Opening issues

You can [open 3 types of issues](https://github.com/Qiskit/qiskit-serverless/issues/new/choose):

* Bug reports: for reporting a misfunction. Provide steps to reproduce and expected behaviour.
* Enhancement request: to suggest improvements to the current code.
* Feature request: if you have a new use case or feature that we are not supporting.

Core contributors classify the tasks according to its nature and prioritize them
from sprint to sprint. Types are not mutually exclusive and can change over time
if needed.

Security vulnerabilities must be privately reported by following our [Security Policy](SECURITY.md).


## Contributing code

### Tools

You'll need to install these tools on your development environment:

1. [python](https://www.python.org/): the language qiskit-serverless is written in (Note that we currently support Python >=3.9,<=3.13).
1. [git](https://git-scm.com/): for source control
1. [docker](https://docs.docker.com/engine/install/) or [podman](https://podman.io/): for building dev environment
1. [kubectl](https://kubectl.docs.kubernetes.io/): for interacting with Kubernetes clusters
1. [helm](https://helm.sh/): to install qiskit-serverless on Kubernetes
1. [tox](https://tox.wiki/en): to run tests and build the documentation
1. [pre-commit](https://pre-commit.com/): to run linting checks automatically on commit/push

Note: Installing the `pip` and `venv` python libraries will also be useful

#### For non-Linux users
To simplify the steps required to build and deploy qiskit-serverless, we recommend the use of virtual machines for runtime containers.

If you are on a Windows machine, it is recommended to use [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/install).

If you are on a Mac machine, it is recommended to use [Colima](https://github.com/abiosoft/colima) to run docker and kubernetes container environments. It automatically installs [`containerd`](https://github.com/containerd/containerd) runtime and provides support for `nerdctl`, a CLI tool for `containerd`. Colima can be set up as follows:

```bash
brew install colima
brew install docker
colima start --cpu 4 --memory 8
```
To check if colima is running:
```bash
colima status
```

To list running containers:
```bash
nerdctl ps -a
```

To list container images:
```bash
nerdctl images
```

### Deciding what to work on

To give our collaborators an idea of where the team needs help, we use the
[help wanted](https://github.com/Qiskit/qiskit-serverless/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22)
label – this is appropriate for all contributors. In addition, for those who are relatively new to the open-source
workflow or our codebase, feel free to view issues tagged with the
[good first issue](https://github.com/Qiskit/qiskit-serverless/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
label.


### Clone the repo

So you decided to get your hands dirty and start working on a patch? Then you
need to know that the project follows the
[Forking Workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/forking-workflow)
with [Feature Branches](https://www.atlassian.com/git/tutorials/comparing-workflows/feature-branch-workflow).

The above means we expect you to fork the project on your own GitHub account and make your `main` branch to
track this repository. A typical Git setup after
[forking the project](https://docs.github.com/en/free-pro-team@latest/github/getting-started-with-github/fork-a-repo) is:

```sh
# After forking the repository in GitHub
git clone https://github.com/<your_username>/qiskit-serverless.git
cd qiskit-serverless
git remote add upstream https://github.com/Qiskit/qiskit-serverless.git
git remote set-url --push upstream no_push
git remote update upstream
git checkout main
git branch -u upstream/main
git pull
```

As a core contributor due to some access limitations between forks and the head branch we encourage you to
[clone](https://support.atlassian.com/bitbucket-cloud/docs/clone-a-repository/) the repository
instead of forking it.

### Development environment

This repository contains several projects with different technologies. Depending on the project that you selected (eg. gateway), from the project directory you will run:
- `pip install -r requirements.txt -r requirements-dev.txt` for python projects (strongly consider using a [virtual environment](https://docs.python.org/3/library/venv.html)!).
- `helm dependency build` for helm (Before running this command, make sure to check for helm configuration instructions specific to your selected project charts).
-  `terraform init` for terraform.

#### Setting up pre-commit hooks

We use [pre-commit](https://pre-commit.com/) to automatically run linting checks. To set it up (required once per local clone):

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

**How it works:**
- **On commit:** Black auto-formats your staged Python files. If files are modified, the commit will fail — simply `git add` the changes and commit again.
- **On push:** Pylint and mypy run automatically (same checks as CI).

This ensures your code passes linting before reaching CI, saving time on failed builds.

To set up a local development environment for the qiskit-serverless components (including the gateway, repository, ray nodes, etc.) using the latest changes you've made, use `docker compose` or `podman-compose`.

To build the images, run the following command from the root directory:

```docker compose -f docker-compose-dev.yaml build```

And to deploy your code, run the following command:

```docker compose -f docker-compose-dev.yaml up```

If you wish to rebuild only a specific component (for example, the `gateway`), you can do so as follows:

```docker compose -f docker-compose-dev.yaml build gateway```

### Assigning yourself

The very first step to working on an issue is
[assigning yourself](https://docs.github.com/en/issues/tracking-your-work-with-issues/assigning-issues-and-pull-requests-to-other-github-users#assigning-an-individual-issue-or-pull-request)
the issue. This gives all contributors the visibility into who is working on what.

In case you are not a contributor just participate in the issue that you are interested to help, and we will
let you know the status of that issue.


### Working on an issue

When you are going to start working on an issue, make sure you are in your `main`
branch and that it is entirely up-to-date and create a new branch with a
meaningful name. The typical terminal code for this is:

```sh
git checkout main
git fetch upstream
git rebase upstream main
git checkout -b issue-1234-new-feature
```

Now start adding your changes and remember to commit often:

```sh
git commit
```

And include a summary and some notes or clarifications if needed:

```
Add a new feature.

The new feature will provide the possibility to do something awesome.
```

From time to time, you want to check if your `main` branch is still up-to-date. If not, you will need to
[rebase](https://www.atlassian.com/git/tutorials/rewriting-history/git-rebase)
(or [merge](https://www.atlassian.com/git/tutorials/using-branches/git-merge)), then continue working:

```sh
git checkout main
git fetch upstream
git rebase upstream main
git checkout issue-1234-new-feature
git rebase main issue-1234-new-feature
```


### Adding tests

Our team upholds the philosophy that a healthy codebase will include the proper amount of testing.
From the project you are working on, you can run tests with `tox -epy311`.
Note if you run this command from qiskit-serverless top directory, it will build the project documentation.
For detailed testing guidelines using tox environments, please refer to [this documentation](./client/tests/README.md).

As a part of the development backlog planning, we have internal discussions to determine which scenarios should be
tested. For code that requires testing, please look for notes in the original issues, as we will do our best to
provide ideal, meaningful cases to test.

If you feel that there's a test case that we have not considered, please comment in the
original issue for the team to see.


### Pull requests

Pull requests serve a double purpose:
1. Share the code with the team. So almost everybody is aware of how the code base is evolving.
2. Provide an opportunity for improving code quality.

When you think your work is done, push the branch to your repository:

```sh
git push origin issue-1234-new-feature
# Start a pull request in GitHub
```

And
[create a pull request](https://docs.github.com/en/free-pro-team@latest/github/collaborating-with-issues-and-pull-requests/creating-a-pull-request)
against `main` (or a feature branch).
When creating the pull request, provide a description and
[link with the issue that is being solved](https://docs.github.com/en/free-pro-team@latest/github/managing-your-work-on-github/linking-a-pull-request-to-an-issue).

Linking the issue has the advantage of automatically closing the related issue when the pull
request is merged.


### Code review

When you open a PR you will see a template in the pull request body. Please read it carefully and fill in the necessary
information to help the code review process go smoothly.

Once you have sent a PR, the code contributors get notified, and there may be a code
review. The code review helps to solve implementation, semantic and maintainability issues.

The repository also contains some automated checks such as tests and
[linting](#solving-linting-issues). For a pull request to be ready for merging it needs to
**pass automatic checks and have, at least, one positive review**.

During code reviews, there are two prominent roles: the reviewer and the contributor.
The reviewer acts as the keeper of best-practices and code quality, asking
clarifying questions, highlighting implementation errors and recommending changes.
We expect the contributor to take recommendations seriously and be willing to
implement suggested changes or take some other action instead.

Notice we don't expect the contributors to address **all** the comments, nor
the reviewer highlight **all** the issues, we hope both take some compromises to provide
as much value and quality as it fits in the estimated effort.

We don't expect discussions to happen in the pull requests. If there is a disagreement,
our recommendation is for the contributor to yield to the reviewer and for the reviewer
to suggest other alternatives.


### Merging

Once all automated checks are passing and there is a positive review, the pull request
can be merged. If you are an external contributor, expect your PR to be merged by
a core contributor.


## Code style

Code in this repository should conform to [PEP8](https://peps.python.org/pep-0008/) standards.
Style/lint checks are run to validate this. Line length must be limited to no more than 88 characters.

**Readability** is what we value most. We expect reviewers to pay special attention on readability
so at least they can understand new contributions to the codebase.


### Solving linting issues

If you have [set up pre-commit hooks](#setting-up-pre-commit-hooks), linting runs automatically:
- **Black** formats your code on every commit
- **Pylint/mypy** check your code before each push

You can also run linting manually. This repository contains several projects and depending on the project you will need to run:
- `tox -elint` for python projects (from the project directory: `gateway/`, `client/`, or `tests/`).
- `helm lint` for the helm project.
- `terraform validate` for the terraform project.

Notice that, although some linting issues are reported as warnings, we don't usually allow any warning in our code base, so you will need to solve those problems for your contribution to pass the checks.

In the case you need to [disable a rule](https://pylint.readthedocs.io/en/latest/user_guide/messages/message_control.html#block-disables),
please provide an explanation supporting why the exception.


## Final words

Thank you for reading until the end of the document! Abiding by these guidelines you
express your willing in collaborating and contributing in a healthy way. Thanks for
that too!
