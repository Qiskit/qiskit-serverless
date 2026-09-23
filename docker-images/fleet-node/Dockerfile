# syntax=docker/dockerfile:1.17
# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
#
# Fleets worker image (Python 3.12) — the Fleets-runner counterpart of
# docker-images/ray-node/Dockerfile, split into these stages:
#   base:     slim public image (client only, no dynamic deps). Function providers
#             build custom Fleets images FROM it.
#   selector: base + requirements-dynamic-dependencies.txt (the qiskit workload
#             stack). The full runtime the gateway deploys for imageless Fleets
#             jobs, and what the integration-test worker
#             (tests/fleets/fleet-worker/Dockerfile) builds FROM, so the test runs
#             against the production runtime. It is the LAST stage, so a build with
#             no --target resolves to it.
#
# Build from repo root (client/ must be in the build context):
#   docker build --platform linux/amd64 -f docker-images/fleet-node/Dockerfile -t fleet-node:latest .                 # full (selector)
#   docker build --platform linux/amd64 --target base -f docker-images/fleet-node/Dockerfile -t fleet-node:base .     # slim base
#
# No CUDA base image and no driver install: the CUDA libraries come from the
# wheels in requirements-dynamic-dependencies-gpu.txt, and CE's NVIDIA container
# runtime injects the driver + nvidia-smi into GPU workers at runtime. UBI9
# (glibc 2.34) satisfies the mthree manylinux_2_34 wheel. Most pinned deps ship
# linux/x86_64 wheels for 3.12; the two that do not are compiled in the builder
# stage, which is the only place a build toolchain exists.
FROM registry.access.redhat.com/ubi9-minimal:9.8-1789546276 AS base
ARG PYTHON_VERSION=3.12
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python and set up interpreter/pip symlinks (all bound to ${PYTHON_VERSION}).
RUN microdnf update -y && \
    microdnf install -y \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-devel \
        wget-1.21.1 && \
    microdnf clean all && \
    ln -s /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3 && \
    ln -s /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python && \
    ln -s /usr/bin/pip${PYTHON_VERSION} /usr/local/bin/pip3 && \
    ln -s /usr/bin/pip${PYTHON_VERSION} /usr/local/bin/pip

USER 0
# /function_user_data, /job_user_data, /function_provider_data, /job_provider_data
# are the Fleets runner 4-mount COS path layout. fleet-node runs Fleets jobs only,
# so it does not create the Ray runner's /data and /function_data mounts.
#
# NOTE: keep this a plain '&&' chain — do not put '#' comments between the
# continued commands, or a broken chain could silently skip the pip upgrade.
RUN mkdir /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    chown 1000:1000 /function_user_data /job_user_data /function_provider_data /job_provider_data && \
    python${PYTHON_VERSION} -m ensurepip --upgrade && \
    pip install --upgrade --no-cache-dir \
        "pip>=26.1.2" \
        "setuptools>=83.0.0"

# Install the client into the base stage (plain, no [ray] extra — Fleets does not
# use Ray) so images built FROM base — custom provider images and the
# integration-test worker — already have the client. Keep this on its own RUN
# with plain '&&' so a failed install fails the build — do NOT chain '|| true'
# guards onto this step (that would silently ship an image with no client).
# (No symengine lib/lib64 copy: Qiskit 2.2 dropped symengine, so it is not
# installed here; ray-node/gateway removed the same copy in 0.34.0.)
COPY client /tmp/qs
RUN pip install --no-cache-dir /tmp/qs && \
    rm -rf /tmp/qs
USER 1000

# Dynamic dependencies — the qiskit workload stack pre-baked so Fleets functions
# run without reinstalling. requirements-dynamic-dependencies.txt is shared with
# ray-node so the two runners cannot drift, and the gateway reads that same file
# for GET /api/v1/dependencies-versions. The GPU pins live in a second file that
# the gateway does NOT read, so the CUDA packages ship in the image without being
# advertised as dependencies a function on a CPU compute profile could request.
#
# The openmpi wheel is a native library, not an importable package: it exists so
# mpi4py has an MPI to dlopen (mpi4py ships prebuilt MPI.openmpi/MPI.mpich .so
# files and bundles no libmpi of its own). The RPM is not an option, since UBI
# repos carry neither openmpi nor mpich. The wheel installs libmpi.so under pip's
# /usr/local prefix, which is not on the x86_64 loader path (/lib64, /usr/lib64),
# so ldconfig has to pick it up or `import mpi4py.MPI` fails at runtime even
# though pip install succeeded. LD_LIBRARY_PATH would work too, but it is
# inherited by every user function process and can shadow libraries a function
# bundles itself. One entry is enough: the wheel's own support libraries live in
# /usr/local/lib/openmpi/ and resolve through libmpi.so.40's $ORIGIN-relative
# rpath, not through the loader cache, so that subdirectory needs no entry of its
# own -- but libmpi.so.40 must never be separated from it.
FROM base AS deps
USER 0
COPY docker-images/requirements-dynamic-dependencies.txt \
     docker-images/requirements-dynamic-dependencies-gpu.txt /tmp/
RUN pip install --no-cache-dir \
        -r /tmp/requirements-dynamic-dependencies.txt \
        -r /tmp/requirements-dynamic-dependencies-gpu.txt && \
    rm /tmp/requirements-dynamic-dependencies.txt \
       /tmp/requirements-dynamic-dependencies-gpu.txt && \
    echo /usr/local/lib > /etc/ld.so.conf.d/mpi-wheel.conf && \
    ldconfig
USER 1000

# Vayesta and sbd-eigensolver, the two packages with no published wheels. They are
# compiled in this throwaway stage so the C/C++ toolchain never reaches the
# shipped image; selector copies the results out of it.
#
# --- sbd-eigensolver ---
# Sdist-only: a header-only vendored C++ library plus one pybind11 binding, so it
# compiles against MPI and BLAS. No MPI RPM is needed: the openmpi wheel from
# requirements-dynamic-dependencies.txt is a complete Open MPI tree under pip's
# /usr/local prefix (include/mpi.h, lib/libmpi.so, bin/mpicc and the
# share/openmpi wrapper data), and its setup.py trusts MPI_HOME as soon as
# $MPI_HOME/include/mpi.h exists. BLAS_LIB_PATH points at openblas-devel's
# libopenblas (-lopenblas is that setup.py's default). SBD_BUILD_BACKEND=cpu is
# explicit: 'auto' resolves to CPU here anyway since there is no nvc++, but
# pinning it keeps the build deterministic if NVHPC ever lands in this image.
# No libomp: its -lomp branch is macOS-only, Linux builds -fopenmp against
# libgomp. setup.py embeds -Wl,--rpath for each library dir, so the extension
# locates libmpi and libopenblas itself at runtime.
#
# --- Vayesta ---
# It is not on PyPI, so it is installed from the release tarball, and its metadata
# pins `pyscf @ git+https://github.com/pyscf/pyscf@master` (still true on their
# default branch), which would replace the pinned pyscf==2.13.1 with an unpinned
# source build on every rebuild. --no-deps blocks that: numpy, scipy and h5py come
# from requirements-dynamic-dependencies.txt and cvxpy from the -build.txt one. Verified
# against pyscf 2.13.1 with an H2/STO-3G EWF-CCSD run, so the git-master pin is
# not needed in practice.
#
# openblas-devel is build-time only (BLAS is the one hard requirement of
# vayesta/libs/CMakeLists.txt) and puts its headers in /usr/include/openblas, off
# the default include path, while vayesta/libs/core does #include "cblas.h".
# COMPILER_SUPPORTS_MARCH_NATIVE=FALSE suppresses the -march=native that the same
# CMakeLists adds, which would compile for the build machine's CPU and risk SIGILL
# on other Code Engine hardware; CHECK_C_COMPILER_FLAG skips its probe when the
# result is already cached, and setup.py forwards CMAKE_CONFIGURE_ARGS to cmake.
# Vayesta's MANIFEST.in omits vayesta/logo.txt, so without the wget every import
# logs an ERROR banner. The --hash pins the exact tarball bytes of the v1.0.1
# release, so a rebuild fails loudly instead of silently installing something
# else if that tag were ever recreated pointing at a different commit.
FROM deps AS builder
USER 0
ENV CMAKE_CONFIGURE_ARGS="-DCOMPILER_SUPPORTS_MARCH_NATIVE=FALSE" \
    C_INCLUDE_PATH=/usr/include/openblas \
    MPI_HOME=/usr/local \
    BLAS_LIB_PATH=/usr/lib64 \
    SBD_BUILD_BACKEND=cpu
COPY docker-images/requirements-dynamic-dependencies-build.txt /tmp/
# sbd-eigensolver declares setuptools, wheel, pybind11 and mpi4py as PEP 517 build
# requirements, and pip puts those in an isolated build environment rather than in
# site-packages. That matters because selector copies this stage's site-packages
# wholesale, so anything pip installs there ships: isolation is what keeps `wheel`
# out of the image, which the base stage deliberately omits (see the CVE note
# above). pybind11 and mpi4py are in the image regardless, pinned in
# requirements-dynamic-dependencies.txt as sbd's runtime dependencies.
RUN microdnf install -y gcc gcc-c++ make cmake openblas-devel && \
    microdnf clean all && \
    pip install --no-cache-dir \
        -r /tmp/requirements-dynamic-dependencies-build.txt && \
    rm /tmp/requirements-dynamic-dependencies-build.txt
# Vayesta on its own RUN because it installs by URL with --no-deps rather than
# from the pins above, and needs the logo.txt backfill afterwards. --hash is only
# accepted by pip inside a requirements file, not as a bare install argument, so
# the pinned requirement is written to one line of a throwaway file first.
RUN echo "https://github.com/BoothGroup/Vayesta/archive/refs/tags/v1.0.1.tar.gz --hash=sha256:984021514b0293e11d3adca0d9a3d7ee8f399aa170aca64f349822af62dd325f" \
        > /tmp/vayesta-requirement.txt && \
    pip install --no-cache-dir --no-deps -r /tmp/vayesta-requirement.txt && \
    rm /tmp/vayesta-requirement.txt && \
    wget -qO "$(python -c 'import sysconfig; print(sysconfig.get_paths()["platlib"])')/vayesta/logo.txt" \
        https://raw.githubusercontent.com/BoothGroup/Vayesta/v1.0.1/vayesta/logo.txt

# The shipped image: deps plus the two compiled packages and the runtime halves of
# what they linked against, and nothing from the toolchain. The site-packages trees
# are copied wholesale because compiled extensions land in platlib (lib64) while
# pure-python deps land in purelib (lib); the toolchain is installed by microdnf,
# not pip, so it stays behind in builder.
#
FROM deps AS selector
USER 0
RUN microdnf install -y openblas libgomp git-core && \
    microdnf clean all
COPY --from=builder /usr/local/lib/python3.12/site-packages/ \
                    /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/lib64/python3.12/site-packages/ \
                    /usr/local/lib64/python3.12/site-packages/
USER 1000
