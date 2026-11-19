# Fleets Runtime Images — CPU / GPU Split Specification

## Relevant files

| File | Role |
|------|------|
| `docker-images/fleet-node/Dockerfile` | All Fleets runtime stages: `base`, `deps`, `builder`, `selector`, `selector-gpu` |
| `docker-images/requirements-dynamic-dependencies.txt` | The shared qiskit workload stack. Also installed by `ray-node`, and read by the gateway as the `GET /api/v1/dependencies-versions` allow-list |
| `docker-images/requirements-dynamic-dependencies-gpu.txt` | The CUDA pins. Installed by `selector-gpu` only, and deliberately **not** read by the gateway |
| `docker-images/requirements-dynamic-dependencies-build.txt` | Pins for `builder` only (`cvxpy`, `sbd-eigensolver`) |
| `Makefile` | `build-fleet-node`, `build-fleet-node-local`, `build-fleet-selector`, `build-fleet-selector-gpu` |
| `.github/workflows/build-containers-test.yaml` | Builds `selector` and `selector-gpu` on every PR |
| `.github/workflows/fleets-integration-tests.yaml` | Builds `base` and `selector` for the smoke tests |
| `.github/workflows/update-component-versions.yaml` | Bumps the `fleet-selector` / `fleet-selector-gpu` tags in `values.yaml` and `settings.py` on release |
| `tests/fleets/fleet-worker/Dockerfile` | Mock CE worker, `FROM fleet-node:latest` (the CPU stage) |
| `gateway/core/services/runners/fleets_runner.py` | `_get_image()` — picks the image for a job from its compute profile |
| `gateway/main/settings.py` | `FLEETS_DEFAULT_IMAGE` (CPU) and `FLEETS_DEFAULT_GPU_IMAGE`, fed from `ce.fleetsDefaultImage` / `ce.fleetsDefaultGpuImage` |

---

## Specification

### 1. Stages

```
base ──> deps ──> builder          CPU toolchain; compiles Vayesta + sbd-eigensolver. Never ships.
            │
            └──> selector ──> selector-gpu
                 (CPU)          (CPU + CUDA)
```

- **`base`** — Python 3.12 on `ubi9-minimal`, plus the client. No dynamic
  dependencies. Function providers build custom Fleets images `FROM` it.
- **`deps`** — `base` + the shared workload stack. CPU only. Both selectors rest
  on it.
- **`builder`** — `deps` + a C/C++ toolchain, for the two packages with no
  published wheels. Compiles against the CPU stack (`SBD_BUILD_BACKEND=cpu`), so
  both shipped images take its output through `selector`'s `COPY --from=builder`.
- **`selector`** — the CPU runtime. Shipped.
- **`selector-gpu`** — `selector` + the CUDA pins. Shipped.

`selector-gpu` is **last**, so a build with no `--target` resolves to it. The
order is forced, since `selector-gpu` is `FROM selector`. Every build site in the
repo therefore passes `--target` explicitly.

### 2. Published images

| Image | Stage | Contents |
|-------|-------|----------|
| `fleet-node` | `selector-gpu` | Workload stack **+ CUDA** |
| `fleet-selector` | `selector` | Workload stack, no CUDA |
| `fleet-selector-gpu` | `selector-gpu` | Workload stack + CUDA |

`fleet-node` still carries CUDA so that any deployment left pointing at it keeps
working. It is no longer what the gateway deploys, though: `FLEETS_DEFAULT_IMAGE`
(`gateway/main/settings.py`) and the chart's `ce.fleetsDefaultImage` now resolve
to `fleet-selector`, the CPU runtime, and the new `FLEETS_DEFAULT_GPU_IMAGE` /
`ce.fleetsDefaultGpuImage` resolve to `fleet-selector-gpu`. `_get_image()` picks
between the two per job, so a CPU job no longer pulls the CUDA half.

### 2a. How a job gets its image

`_get_image(wants_gpu)` (`gateway/core/services/runners/fleets_runner.py`):

| Job | Image |
|-----|-------|
| Provider image set, no artifact | `program.image`, whatever the profile |
| Everything else, GPU profile | `FLEETS_DEFAULT_GPU_IMAGE` |
| Everything else, CPU profile | `FLEETS_DEFAULT_IMAGE` |

`wants_gpu` is `bool(scale_gpu)` from the `_parse_compute_profile()` call that
`_create_fleet()` already makes — the same parse that builds the fleet's GPU
request. One parse feeds both, so the image and the GPU allocation cannot
disagree: a job on the GPU image is always a job that asked Code Engine for a
GPU. Re-matching the profile string in `_get_image()` would reintroduce exactly
that drift.

A provider image is the provider's choice and is never substituted — the gateway
does not know which accelerators a provider's container carries.

**An unset `FLEETS_DEFAULT_GPU_IMAGE` fails the submit** rather than falling back
to the CPU image. The fallback is the failure mode the split had to avoid in the
first place: the job lands on a GPU worker, `import gpu4pyscf` fails, the
chemistry function finishes on CPU, and the job still reports success. Nothing
downstream flags it, so a loud `RunnerError` at submit is the only place the
misconfiguration is visible. CPU jobs are unaffected when it is unset.

### 3. Why the CUDA pins are a separate file

Three reasons, all still load-bearing:

1. **Image size.** Fleets pulls the runtime image once per job. The CUDA wheels
   are ~2.5 GB compressed and 6.5 GB on disk (measured: `selector` 3.4 GB,
   `selector-gpu` 9.9 GB), so a CPU job must not pull them.
2. **The gateway allow-list.** `GET /api/v1/dependencies-versions` is built from
   the shared file only (`gateway/api/utils.py`). Keeping the CUDA packages out
   of it means they are not advertised as dependencies a function on a CPU
   compute profile could request and then fail on for want of a device.
3. **arm64.** `gpu4pyscf-cuda12x` publishes an x86_64 wheel only, while the
   shared file also feeds `ray-node`, which has an arm64 local-dev variant.

### 4. Build-time asserts

The two images are not kept distinct by convention — each stage asserts its own
half, because every way they could drift back together is silent.

| Stage | Assert | Catches |
|-------|--------|---------|
| `selector` | No `nvidia`/`cupy`/`cutensor`/`gpu4pyscf` dir under any site-packages root | A GPU pin added to the shared file; `builder` moved to the GPU side, whose `COPY` would drag CUDA in |
| `selector-gpu` | Its pin set moved no version the CPU image pins | The GPU install resolving a shared pin differently — `cupy-cuda12x` wants `numpy<2.6`, `ffsim` wants `numpy<=2.3` |
| `selector-gpu` | All nine CUDA sonames resolve via `ldconfig -p` | A missing runtime library, which would make GPU jobs fall back to CPU unnoticed |

Two details that are easy to get wrong when editing these:

- **Soname majors track each library, not the CUDA release.** cuFFT is
  `libcufft.so.11`, cuRAND `libcurand.so.10`, cuSOLVER `libcusolver.so.11`, even
  though all three ship in `-cu12` wheels. Read them off the installed wheels
  (`ls site-packages/nvidia/*/lib`) before changing the list.
- **A constraints file cannot replace the pin-drift assert.** pip rejects extras
  in constraints (`Constraints cannot have extras`) and the shared file has
  `qiskit-addon-aqc-tensor[quimb-jax]`.

### 5. Libraries needing an `ldconfig` entry

Both the openmpi and CUDA wheels install shared objects outside the loader path,
so the image has to register them or the `dlopen` fails at import even though
`pip install` succeeded.

| Library | Installed under | Registered by |
|---------|-----------------|---------------|
| `libmpi.so` (openmpi wheel) | `/usr/local/lib` | `deps` |
| `libcublas.so.12` and friends | `site-packages/nvidia/*/lib` | `selector-gpu` |

`LD_LIBRARY_PATH` would also work but is inherited by every user function
process, where it can shadow a library the function bundles itself.

The CUDA dirs are globbed under all three site-packages roots — sysconfig's
`purelib` and `platlib` plus `site.getsitepackages()` — because no single one is
reliable on this base: the wheels are `purelib` while the primary site dir is
`platlib`, and `site.getsitepackages()` is built from `sys.prefix` (`/usr`) while
pip installs under `/usr/local` via the distro's `posix_local` scheme.

### 6. BLAS: `openblas-serial`, not `openblas`

`selector` installs `openblas-serial`. The base `openblas` package in the UBI9
appstream ships documentation and licences only — nine files, zero shared
objects — so installing it leaves `import sbd._core_cpu` failing on
`libopenblas.so.0: cannot open shared object file`.

The soname lives in the threading-variant subpackages, and only the serial one
spells it `libopenblas.so.0`:

| Package | Provides | In UBI9 appstream |
|---------|----------|-------------------|
| `openblas` | *(no shared objects)* | yes |
| `openblas-serial` | `libopenblas.so.0` | yes |
| `openblas-openmp` | `libopenblaso.so.0` | yes |
| `openblas-threads` | `libopenblasp.so.0` | no |

Neither variant with the extra letter satisfies the `-lopenblas` link that
`builder` records in the extension's `DT_NEEDED`. Verified against
`cdn-ubi.redhat.com/content/public/ubi/dist/ubi9/9/x86_64/appstream`, the same
metadata `microdnf` resolves against.

Serial is also the right variant on its own merits: `sbd-eigensolver` takes its
parallelism from `-fopenmp`/`libgomp`, and a threaded BLAS under a threaded
caller nests thread teams and oversubscribes a CPU-limited Code Engine
container.

### 7. CI coverage

| Workflow | Builds | Notes |
|----------|--------|-------|
| `.github/workflows/build-containers-test.yaml` | `selector`, `selector-gpu` | The GPU leg uses `outputs: type=cacheonly` — the build runs and the asserts fire, but the 9.9 GB image is never exported. It also reclaims ~10 GB of preinstalled runner toolchains first |
| `.github/workflows/fleets-integration-tests.yaml` | `base`, `selector` | The smoke tests run against the CPU runtime |

The GPU leg takes its own check label, `fleet-node/Dockerfile (gpu)`, because the
check name embeds `matrix.label` and the branch ruleset matches required checks
by exact string — a new label adds a check rather than renaming an existing one.

`import cupy` / `import gpu4pyscf` is **not** covered: no GitHub runner has a
GPU. That has to be exercised on a GPU compute profile after publication.

---

## Design decisions

**Why `selector-gpu` is `FROM selector` rather than both being `FROM deps`.**
It makes the GPU image provably a superset of the CPU one, and it is what lets
the pin-drift assert work at all: the CPU pin set is written to `/opt/cpu-pins.txt`
in `selector` and inherited, so the comparison needs no `COPY --from` and cannot
go stale. The cost is that the CUDA wheels install after `ray[default]` and after
`builder`'s `COPY`s, inverting the old single-image order — which is exactly the
risk the assert covers.

**Why the asserts live in the stages rather than in a test.** They guard against
edits to this Dockerfile and to the requirements files, and the failures they
catch are invisible at runtime — a job that silently runs on CPU still succeeds.
A build-time failure is the only place the signal is loud. It also means the
public repo's CI covers the GPU stage without needing a GPU.

**Why the integration tests track the CPU image.** The two images differ only by
the CUDA wheels, which a test worker with no GPU cannot exercise, and which would
add 6.5 GB to every local run. `make build-fleet-node-local` exists for this: it
builds `selector` and applies the bare `fleet-node:latest` tag the harness
expects. `make build-fleet-node` builds the published GPU image, which has no
aarch64 wheel and so cannot be built on Apple Silicon at all.

---

## Known gaps

- **Nothing asserts the GPU image actually runs a GPU job.** The image choice is
  unit-tested, but `import cupy` / `import gpu4pyscf` still needs a GPU compute
  profile to exercise, and no CI runner has one. Until that is done, a broken
  `fleet-selector-gpu` looks identical to a working one from CI's point of view.
- **The two default settings must be configured as a pair.** A deployment that
  overrides `ce.fleetsDefaultImage` and forgets `ce.fleetsDefaultGpuImage` fails
  every GPU-profile submit. The failure is loud and names the setting, but it is
  a submit-time failure rather than a deploy-time one — nothing validates the
  pair at startup.
- **The release pipeline is not in this repo.** `ci/scripts/build-artifact.sh`
  needs `build_image` / `install_test_image` / `push_image` / `save_image`
  entries for the new target in both the staging and production branches, and the
  registry for `fleet-selector-gpu` has to be decided — note the existing split,
  `fleet-node` to `icr.io/quantum-public/...` and `fleet-selector` to
  `icr.io/qc-middleware-prod/...`.
- **GPU image size.** The CUDA wheels are shipped whole. zstd layer compression
  and `nvprune`-ing the device code for architectures we do not schedule on are
  both unexplored.
- **Fleets jobs run with cwd `/`.** No `WORKDIR` is set and neither job wrapper
  passes `cwd=` to `Popen`, so a user function runs in a directory uid 1000
  cannot write. `import vayesta` creates a log file in cwd at import, so it fails
  there. Masked everywhere it would normally surface: the test worker sets
  `WORKDIR /app` and runs as root, Ray supplies its own working dir, and
  `ray-node` does not carry Vayesta.
