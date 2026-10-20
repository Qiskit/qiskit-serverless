# syntax=docker/dockerfile:1.28
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
# docker-images/ray-node/Dockerfile. Three of its stages ship:
#   base:         slim public image (client only, no dynamic deps). Function
#                 providers build custom Fleets images FROM it.
#   selector:     base + requirements-dynamic-dependencies.txt (the qiskit
#                 workload stack), CPU only. The runtime the gateway deploys for
#                 imageless Fleets jobs, and what the integration-test worker
#                 (tests/fleets/fleet-worker/Dockerfile) builds FROM, so the test
#                 runs against the production runtime.
#   selector-gpu: selector + requirements-dynamic-dependencies-gpu.txt (the CUDA
#                 stack). Same workload stack as selector, for jobs on a GPU
#                 compute profile.
# deps and builder are intermediate: deps is the shared pip layer both selectors
# rest on, builder holds the C/C++ toolchain and never ships.
#
# The CUDA wheels are ~2.5 GB compressed, and Fleets pulls the image once per
# job, so they are confined to selector-gpu: a CPU job must not pay that pull
# cost for wheels it never imports. Nothing enforces that split at runtime, so
# the selector stage asserts it carries no CUDA payload and selector-gpu asserts
# every library gpu4pyscf dlopens resolves — see those stages.
#
# selector-gpu is the LAST stage, so a build with no --target resolves to the GPU
# image. CPU builds must pass --target selector explicitly; build-fleet-node and
# build-fleet-selector in the Makefile and both CI workflows do. The order is
# forced -- selector-gpu is FROM selector, so it cannot be declared first -- which
# is why the default is the GPU image rather than the more obvious CPU one.
#
# Build from repo root (client/ must be in the build context):
#   docker build --platform linux/amd64 --target selector -f docker-images/fleet-node/Dockerfile -t fleet-node:latest .        # CPU runtime
#   docker build --platform linux/amd64 --target selector-gpu -f docker-images/fleet-node/Dockerfile -t fleet-node:gpu .       # CUDA runtime
#   docker build --platform linux/amd64 --target base -f docker-images/fleet-node/Dockerfile -t fleet-node:base .              # slim base
#
# No CUDA base image and no driver install: the CUDA libraries come from the
# wheels in requirements-dynamic-dependencies-gpu.txt, and CE's NVIDIA container
# runtime injects the driver + nvidia-smi into GPU workers at runtime. UBI9
# (glibc 2.34) satisfies the mthree manylinux_2_34 wheel. Most pinned deps ship
# linux/x86_64 wheels for 3.12; the two that do not are compiled in the builder
# stage, which is the only place a build toolchain exists.
FROM registry.access.redhat.com/ubi9-minimal:9.8-1791808450 AS base
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
# Always USER 1000:1000, never a bare USER 1000: uid 1000 has no /etc/passwd entry
# here, so without an explicit group the runtime assigns gid 0 (root group), and
# Code Engine Fleets has no runAsGroup to override it.
USER 1000:1000

# Dynamic dependencies — the qiskit workload stack pre-baked so Fleets functions
# run without reinstalling. requirements-dynamic-dependencies.txt is shared with
# ray-node so the two runners cannot drift, and the gateway reads that same file
# for GET /api/v1/dependencies-versions. This stage is CPU only and is what both
# shipped selectors rest on; the CUDA pins are installed by selector-gpu alone,
# from a second file the gateway does NOT read, so they never become dependencies
# a function on a CPU compute profile could request and then fail on for want of
# a device.
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
COPY docker-images/requirements-dynamic-dependencies.txt /tmp/
RUN pip install --no-cache-dir \
        -r /tmp/requirements-dynamic-dependencies.txt && \
    rm /tmp/requirements-dynamic-dependencies.txt && \
    echo /usr/local/lib > /etc/ld.so.conf.d/mpi-wheel.conf && \
    ldconfig
USER 1000:1000

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

# The shipped CPU image: deps plus the two compiled packages and the runtime
# halves of what they linked against, and nothing from the toolchain. The
# site-packages trees are copied wholesale because compiled extensions land in
# platlib (lib64) while pure-python deps land in purelib (lib); the toolchain is
# installed by microdnf, not pip, so it stays behind in builder.
#
# Also the base selector-gpu adds the CUDA stack to, so everything here is in
# both shipped images and anything CPU-specific would have to go after the FROM
# below instead.
FROM deps AS selector
USER 0
RUN microdnf install -y openblas libgomp git-core && \
    microdnf clean all
COPY --from=builder /usr/local/lib/python3.12/site-packages/ \
                    /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/lib64/python3.12/site-packages/ \
                    /usr/local/lib64/python3.12/site-packages/
# Ray for selector only (base stays client-only). Constraint must match the
# client's [ray] extra in client/pyproject.toml. Not in
# requirements-dynamic-dependencies.txt: that file is gateway-advertised and
# shared with ray-node. After the builder COPYs so they cannot clobber it.
RUN pip install --no-cache-dir "ray[default]>=2.58.0,<3"

# This image must carry no CUDA payload: that is the whole point of the split,
# and ~2.5 GB of pull time per CPU job rests on it. Asserted rather than trusted
# because the ways it could come back are all quiet ones -- a GPU pin added to
# the shared requirements file instead of the -gpu one, or builder moved onto the
# GPU side, in which case the COPYs above would drag a CUDA tree in here without
# a single line of this stage changing.
#
# Globbed under every site-packages root pip could have installed into:
# sysconfig's purelib and platlib (the same source the Vayesta step above trusts)
# plus site.getsitepackages(). All three are needed because no single one is
# reliable here -- the CUDA wheels are purelib while the primary site dir on this
# base is platlib, and site.getsitepackages() is built from sys.prefix (/usr)
# while pip installs under /usr/local via the distro's posix_local scheme.
#
# Dist-info dirs are globbed too, not just the import packages: a CUDA wheel that
# somehow installed with no importable top-level dir would still be a wheel in
# the image, and the nvidia-* ones are precisely the heavy, mostly-.so kind.
#
# A `python -c` one-liner, matching the other embedded scripts in this file,
# rather than the heredoc RUN the syntax directive above would allow: that needs
# BuildKit on Docker and Buildah >= 1.33 on Podman, and nothing else here asks
# for either.
RUN python -c 'import glob, site, sysconfig; roots = {sysconfig.get_paths()[k] for k in ("purelib", "platlib")} | set(site.getsitepackages()); pats = ("nvidia", "nvidia_*", "cupy", "cupy_*", "cutensor", "cutensor_*", "gpu4pyscf", "gpu4pyscf_*"); found = sorted(d for r in roots for p in pats for d in glob.glob(f"{r}/{p}")); assert not found, f"CUDA payload in the CPU image: {found}"; print(f"no CUDA payload under {sorted(roots)}")'
# The CPU pin set, recorded so selector-gpu can prove it did not move any of it
# (see that stage). It works precisely because selector-gpu is FROM selector: the
# file is inherited, so the comparison needs no COPY --from and cannot go stale.
#
# --format=freeze rather than `pip freeze` because the latter spells a
# URL-installed package as "vayesta @ https://..." and would make the comparison
# depend on install method rather than version. A few KB, and it ships in both
# images, which is no loss: it is the clearest statement of what runtime a given
# image actually has. mkdir -p so this does not rest on /opt existing in the base.
RUN mkdir -p /opt && pip list --format=freeze | sort > /opt/cpu-pins.txt
USER 1000:1000

# The shipped GPU image: the same workload stack as selector plus the CUDA wheels.
# LAST stage on purpose -- see the --target note in the header block.
#
# The CUDA pins go in after selector's ray install and its builder COPYs, where
# the old single-image build had them in before both. pip therefore resolves them
# against an already-populated site-packages, so it could satisfy a CUDA wheel's
# constraint by moving a package the CPU image already pinned -- cupy-cuda12x
# constrains numpy<2.6,>=2.0 while ffsim constrains numpy<=2.3, and a resolution
# inside that overlap is reachable. The result would be two images whose shared
# workload stack is not actually the same stack, which is both a support problem
# and a silent one.
#
# A -c constraints file cannot prevent it: pip rejects extras in constraints
# ("Constraints cannot have extras") and the shared file has
# qiskit-addon-aqc-tensor[quimb-jax]. So it is detected instead. The assert
# compares this stage's pin set against the CPU one recorded above and fails on
# any package whose version moved, listing them; additions are the point of the
# stage and pass. If it ever fires, the fix is to pin the moved package in
# requirements-dynamic-dependencies.txt so both images resolve it the same way --
# not to delete the check.
FROM selector AS selector-gpu
USER 0
COPY docker-images/requirements-dynamic-dependencies-gpu.txt /tmp/
RUN pip install --no-cache-dir \
        -r /tmp/requirements-dynamic-dependencies-gpu.txt && \
    rm /tmp/requirements-dynamic-dependencies-gpu.txt
RUN pip list --format=freeze | sort > /opt/gpu-pins.txt
RUN python -c 'import pathlib; pins = lambda p: dict(l.split("==", 1) for l in pathlib.Path(p).read_text().splitlines() if "==" in l); cpu, gpu = pins("/opt/cpu-pins.txt"), pins("/opt/gpu-pins.txt"); moved = {n: (v, gpu.get(n, "REMOVED")) for n, v in cpu.items() if gpu.get(n) != v}; assert not moved, f"the GPU install moved packages the CPU image pins, so the two images no longer share one workload stack: {moved}. Pin them in requirements-dynamic-dependencies.txt."; print(f"CPU pin set intact ({len(cpu)} packages); GPU adds {len(set(gpu) - set(cpu))}")'

# The nvidia-*-cu12 CUDA wheels need the same ldconfig treatment the openmpi wheel
# gets in deps, and for the same reason: gpu4pyscf dlopens libcublas.so.12 and
# friends at import, and they install under site-packages/nvidia/<component>/lib,
# which is on no default loader path. Their dirs are globbed rather than
# hardcoded, under all three site-packages roots, for the reasons the purity
# assert in selector spells out. The assert turns "found nothing" into a failure
# at this line rather than an empty .conf and a puzzling loader error further
# down, and the cat puts the registered dirs in the build log.
RUN python -c 'import glob, site, sysconfig; roots = {sysconfig.get_paths()[k] for k in ("purelib", "platlib")} | set(site.getsitepackages()); dirs = sorted(d for r in roots for d in glob.glob(f"{r}/nvidia/*/lib")); assert dirs, f"no nvidia/*/lib dirs under {sorted(roots)}"; print("\n".join(dirs))' \
        > /etc/ld.so.conf.d/nvidia-wheels.conf && \
    cat /etc/ld.so.conf.d/nvidia-wheels.conf && \
    ldconfig

# Every CUDA shared object gpu4pyscf dlopens must be in the loader cache. This is
# asserted rather than assumed because the failure mode is invisible: a missing
# library fails `import gpu4pyscf`, the chemistry function falls back to CPU, and
# the job still succeeds -- so nothing downstream of the build would notice that
# GPU jobs stopped using their GPU.
#
# It is a loader-cache check and not `import gpu4pyscf` on purpose: the build
# runners have no CUDA device, so an import would risk failing for reasons that
# have nothing to do with these libraries. ldconfig -p prints one
# "<soname> (abi) => <path>" line per cached entry, hence the trailing " (" in the
# match -- a bare soname would also match longer names such as
# libnvrtc-builtins.so.12.9.
#
# Mind the soname majors: they track each library's own version, not the CUDA
# release, so cuFFT is libcufft.so.11, cuRAND libcurand.so.10 and cuSOLVER
# libcusolver.so.11 even though all three ship in -cu12 wheels. Read them off the
# installed wheels (ls site-packages/nvidia/*/lib) before editing this list; the
# ".so.12" spelling looks right and is wrong for three of the nine.
RUN for lib in libcublas.so.12 libcublasLt.so.12 libcudart.so.12 libcufft.so.11 \
               libcurand.so.10 libcusolver.so.11 libcusparse.so.12 \
               libnvJitLink.so.12 libnvrtc.so.12; do \
        ldconfig -p | grep -qF "$lib (" || \
            { echo "FATAL: $lib missing from the loader cache -- gpu4pyscf would silently fall back to CPU"; exit 1; }; \
    done
USER 1000:1000
