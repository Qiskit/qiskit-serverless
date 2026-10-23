# This code is part of a Qiskit project.
#
# (C) Copyright IBM and Cleveland Clinic Foundation 2025
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
#
# Copied from qiskit-community/qiskit-function-templates chemistry/sqd_pcm at 933180d87 and
# altered for the qiskit-serverless performance test: it logs the UTC start time before the
# imports, and use_fake_backend picks a FakeHanoiV2 backend with the saved counts instead of a QPU.

"""
SQD-PCM Function Template source code.
"""
import datetime as _perf_datetime  # pylint: disable=wrong-import-order

# only in the main process: each spawn worker imports this file again as __mp_main__
if __name__ == "__main__":
    print(f"perf-start {_perf_datetime.datetime.now(_perf_datetime.timezone.utc).isoformat()}", flush=True)

# pylint: disable=wrong-import-position
# The thread-env setup below must run before numpy/pyscf are imported (they read
# these vars at load time), so the imports that follow it are intentionally not
# at the very top of the module.
import os


def _default_blas_threads() -> None:
    """Default BLAS/OpenMP to 1 thread before numpy/pyscf import. Prevents
    N-workers x N-threads oversubscription; overridden per worker later."""
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(var, "1")


_default_blas_threads()

from pathlib import Path
from typing import Any
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import sys
import json
import time
import traceback
import numpy as np

import ffsim

from pyscf import gto, scf, mcscf, ao2mo, tools, cc
from pyscf.lib import chkfile
from pyscf.mcscf import avas
from pyscf.solvent import pcm

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.primitives import BackendSamplerV2

from qiskit_addon_sqd.counts import counts_to_arrays
from qiskit_addon_sqd.configuration_recovery import recover_configurations
from qiskit_addon_sqd.fermion import bitstring_matrix_to_ci_strs
from qiskit_addon_sqd.subsampling import (
    postselect_by_hamming_right_and_left,
    subsample,
)

from qiskit_ibm_runtime import SamplerV2
from qiskit_serverless import (
    get_arguments,
    save_result,
    update_status,
    Job,
    get_runtime_service,
    get_logger,
)

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
from solve_solvent import solve_solvent

# pylint: enable=wrong-import-position

logger = get_logger()


def _worker_warmup(_):
    """No-op submitted once per worker to force (and time) spawn + PySCF import,
    so the breakdown separates worker startup from solve time."""
    return os.getpid()


def _solve_solvent_worker(args):
    """Run one ``solve_solvent`` batch in a worker process. Module-scope (not a
    closure) so ProcessPoolExecutor can pickle it; takes one positional tuple."""
    (
        batch,
        myeps,
        mysolvmethod,
        myavas,
        num_orbitals,
        spin_sq,
        max_davidson,
        checkpoint_file,
    ) = args
    return solve_solvent(  # sqd for pyscf
        batch,
        myeps,
        mysolvmethod,
        myavas,
        num_orbitals,
        spin_sq=spin_sq,
        max_davidson=max_davidson,
        checkpoint_file=checkpoint_file,
    )


def run_function(
    backend_name: str,
    molecule: dict,
    solvent_options: dict,
    sqd_options: dict,
    lucj_options: dict | None = None,
    **kwargs,
) -> dict[str, Any]:
    """
    Main entry point for the SQD-PCM (Polarizable Continuum Model) workflow.

    This function encapsulates the end-to-end execution of the algorithm.

    Args:
        backend_name: Identifier for the target backend, required for all
            workflows that access IBM Quantum hardware.

        molecule: dictionary with molecule information:
            - "atom" (str): required field, follows pyscf specification for atomic geometry.
                For example, for methanol the value would be::

                    '''
                    O -0.04559 -0.75076 -0.00000;
                    C -0.04844 0.65398 -0.00000;
                    H 0.85330 -1.05128 -0.00000;
                    H -1.08779 0.98076 -0.00000;
                    H 0.44171 1.06337 0.88811;
                    H 0.44171 1.06337 -0.88811;
                    '''

            - "number_of_active_orb" (int): required field
            - "number_of_active_alpha_elec" (int): required field
            - "number_of_active_beta_elec" (int): required field
            - "basis" (str): optional field, default is "sto-3g"
            - "verbosity" (int): optional field, default is 0
            - "charge" (int): optional field, default is 0
            - "spin" (int): optional field, default is 0
            - "avas_selection" (list[str] | None): optional field, default is None

        solvent_options: dictionary with solvent options information:
            - "method" (str): required field. Method for computing solvent reaction field
                for the PCM. Accepted values are: "IEF-PCM", "COSMO",
                "C-PCM", "SS(V)PE", see https://manual.q-chem.com/5.4/topic_pcm-em.html
            - "eps" (float): required field. Dielectric constant of the solvent in the PCM.

        sqd_options: dictionary with sqd options information:
            - "sqd_iterations" (int): required field.
            - "number_of_batches" (int): required field.
            - "samples_per_batch" (int): required field.
            - "max_davidson_cycles" (int): required field.

        lucj_options: optional dictionary with lucj options information:
            - "optimization_level" (int): optional field, default is 2
            - "initial_layout" (list[int]): optional field, default is None
            - "dynamical_decoupling" (bool): optional field, default is True
            - "twirling" (bool): optional field, default is True
            - "number_of_shots" (int): optional field, default is 10000

        **kwargs
            Optional keyword arguments to customize behavior. Existing kwargs include:
            - "files_name" (str): optional name for output files (enabled for local testing)
            - "testing_backend" (FakeBackendV2): optional fake backend instance to bypass
                qiskit runtime service instantiation (enabled for local testing)
            - "count_dict_file_name" (str): filename for a "generate once, then reuse"
                LUCJ counts cache. A relative name is resolved against the entrypoint's
                directory, which on the Fleets runner is the function-scoped, writable
                `/function_user_data/` mount (shared across all jobs of this function).
                If the file exists, its counts are read and the QPU is skipped; if it
                does not, the QPU is sampled and the counts are written there for
                subsequent runs to reuse. An absolute path to an existing file is used
                as-is (read-only), which is how the local unit test supplies fixed counts.

    Returns:
        The function should return the execution results as a dictionary with string keys.
        This is to ensure compatibility with ``qiskit_serverless.save_result``.
    """

    # Preparation Step: Input validation.
    # Do this at the top of the function definition so it fails early if any required
    # arguments are missing or invalid.

    # Molecule parsing
    # Required:
    geo = molecule["atom"]
    num_active_orb = molecule["number_of_active_orb"]
    num_active_alpha = molecule["number_of_active_alpha_elec"]
    num_active_beta = molecule["number_of_active_beta_elec"]
    # Optional:
    input_basis = molecule.get("basis", "sto-3g")
    input_verbosity = molecule.get("verbosity", 0)
    input_charge = molecule.get("charge", 0)
    input_spin = molecule.get("spin", 0)
    myavas = molecule.get("avas_selection", None)

    # Solvent options parsing
    myeps = solvent_options["eps"]
    mymethod = solvent_options["method"]

    # LUCJ options parsing
    if lucj_options is None:
        lucj_options = {}
    opt_level = lucj_options.get("optimization_level", 2)
    initial_layout = lucj_options.get("initial_layout", None)
    use_dd = lucj_options.get("dynamical_decoupling", True)
    use_twirling = lucj_options.get("twirling", True)
    num_shots = lucj_options.get("number_of_shots", True)

    # SQD options parsing
    iterations = sqd_options["sqd_iterations"]
    n_batches = sqd_options["number_of_batches"]
    samples_per_batch = sqd_options["samples_per_batch"]
    max_davidson_cycles = sqd_options["max_davidson_cycles"]
    # BLAS threads per worker; None = auto (from cores/workers, below).
    blas_threads_per_worker = sqd_options.get("blas_threads_per_worker", None)

    # kwarg parsing (local testing)
    testing_backend = kwargs.get("testing_backend", None)
    count_dict_file_name = kwargs.get("count_dict_file_name", None)

    files_name = kwargs.get("files_name", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    # Fleets mounts only a few writable dirs. /job_user_data is the writable,
    # job-scoped mount for these scratch files; fall back to cwd for local runs.
    job_data_dir = Path("/job_user_data")
    base_dir = job_data_dir if job_data_dir.is_dir() else Path.cwd()
    output_path = base_dir / "output_sqd_pcm"
    output_path.mkdir(exist_ok=True)
    datafiles_name = str(output_path) + "/" + files_name

    # --
    # Preparation Step: Qiskit Runtime & primitive configuration for
    # execution on IBM Quantum Hardware.

    if testing_backend is None:
        # Initialize Qiskit Runtime Service
        logger.info("Starting runtime service")
        service = get_runtime_service()
        backend = service.backend(backend_name)
        logger.info(f"Backend: {backend.name}")

        # Set up sampler and corresponding options
        sampler = SamplerV2(backend)
        sampler.options.dynamical_decoupling.enable = use_dd
        sampler.options.twirling.enable_measure = False
        sampler.options.twirling.enable_gates = use_twirling
        sampler.options.default_shots = num_shots
        sampler.options.environment.job_tags = ["sqd_pcm_function"]
    else:
        backend = testing_backend
        logger.info(f"Testing backend: {backend.name}")

        # Set up backend sampler.
        # This doesn't allow running with twirling and dd
        sampler = BackendSamplerV2(backend=testing_backend)

    # Once the preparation steps are completed, the algorithm can be structured following a
    # Qiskit Pattern workflow:
    # https://docs.quantum.ibm.com/guides/intro-to-patterns

    # --
    # Step 1: Map
    # In this step, input arguments are used to construct relevant quantum circuits and operators

    start_mapping = time.time()
    update_status(Job.MAPPING)

    # Initialize the molecule object (pyscf)
    logger.info("Initializing molecule object")
    mol = gto.Mole()
    mol.build(
        atom=geo,
        basis=input_basis,
        verbose=input_verbosity,
        charge=input_charge,
        spin=input_spin,
        symmetry=False,
    )  # Not tested for symmetry calculations

    cm = pcm.PCM(mol)
    cm.eps = myeps
    cm.method = mymethod

    mf = scf.RHF(mol).PCM(cm)
    # Generation of checkpoint file for the solute and solvent
    # which will be reused in all subsequent sections
    checkpoint_file_name = str(datafiles_name + ".chk")
    mf.chkfile = checkpoint_file_name
    mf.kernel()

    # Read-in the information about the molecule
    mol = chkfile.load_mol(checkpoint_file_name)

    # Read-in RHF data
    scf_result_dic = chkfile.load(checkpoint_file_name, "scf")
    mf = scf.RHF(mol)
    mf.__dict__.update(scf_result_dic)

    # LUCJ uses isolated solute
    mf.kernel()

    # Initialize orbital selection based on user input
    if myavas is not None:
        orbs = myavas
        avas_out = avas.AVAS(mf, orbs, with_iao=True)
        avas_out.kernel()
        ncas, nelecas = (avas_out.ncas, avas_out.nelecas)
    else:
        ncas = num_active_orb
        nelecas = (
            num_active_alpha,
            num_active_beta,
        )

    # LUCJ Step:
    # Generate active space
    mc = mcscf.CASCI(mf, ncas=ncas, nelecas=nelecas)
    if myavas is not None:
        mc.mo_coeff = avas_out.mo_coeff
    mc.batch = None
    # Reliable and most convenient way to do the CCSD on only the active space
    # is to create the FCIDUMP file and then run the CCSD calculation only on the
    # orbitals stored in the FCIDUMP file.

    h1e_cas, ecore = mc.get_h1eff()
    h2e_cas = ao2mo.restore(1, mc.get_h2eff(), mc.ncas)

    fcidump_file_name = str(datafiles_name + ".fcidump.txt")
    tools.fcidump.from_integrals(
        fcidump_file_name,
        h1e_cas,
        h2e_cas,
        ncas,
        nelecas,
        nuc=ecore,
        ms=0,
        orbsym=[1] * ncas,
    )

    logger.info("Performing CCSD")
    # Read FCIDUMP and perform CCSD on only active space
    mf_as = tools.fcidump.to_scf(fcidump_file_name)
    mf_as.kernel()

    mc_cc = cc.CCSD(mf_as)
    mc_cc.kernel()
    mc_cc.t1  # pylint: disable=pointless-statement
    t2 = mc_cc.t2

    n_reps = 2
    norb = ncas

    if myavas is not None:
        nelec = (int(nelecas / 2), int(nelecas / 2))
    else:
        nelec = nelecas

    alpha_alpha_indices = [(p, p + 1) for p in range(norb - 1)]
    alpha_beta_indices = [(p, p) for p in range(0, norb, 4)]

    logger.info(f"Same spin orbital connections: {alpha_alpha_indices}")
    logger.info(f"Opposite spin orbital connections: {alpha_beta_indices}")

    # Construct LUCJ op
    ucj_op = ffsim.UCJOpSpinBalanced.from_t_amplitudes(
        t2, n_reps=n_reps, interaction_pairs=(alpha_alpha_indices, alpha_beta_indices)
    )
    # Construct circuit
    qubits = QuantumRegister(2 * norb, name="q")
    circuit = QuantumCircuit(qubits)
    circuit.append(ffsim.qiskit.PrepareHartreeFockJW(norb, nelec), qubits)
    circuit.append(ffsim.qiskit.UCJOpSpinBalancedJW(ucj_op), qubits)
    circuit.measure_all()
    end_mapping = time.time()

    # --
    # Step 2: Optimize
    # Transpile circuits to match ISA

    start_optimizing = time.time()
    update_status(Job.OPTIMIZING_HARDWARE)

    pass_manager = generate_preset_pass_manager(
        optimization_level=opt_level,
        backend=backend,
        initial_layout=initial_layout,
    )

    pass_manager.pre_init = ffsim.qiskit.PRE_INIT
    transpiled = pass_manager.run(circuit)

    end_optimizing = time.time()
    logger.info(
        f"Optimization level: {opt_level}, ops: {transpiled.count_ops()}, depth: {transpiled.depth()}"
    )

    two_q_depth = transpiled.depth(lambda x: x.operation.num_qubits == 2)
    logger.info(f"Two-qubit gate depth: {two_q_depth}")

    # --
    # Step 3: Execute on Hardware
    #
    # count_dict_file_name is a "generate once, reuse" counts cache: if the file
    # exists, read it and skip the QPU; otherwise sample on the QPU and write it.
    # A relative name resolves to /function_user_data (function-scoped + writable),
    # so the first run's file is seen by later runs; an absolute path is used as-is
    # (local test). Unset means always sample.
    if count_dict_file_name is not None:
        counts_path = count_dict_file_name
        if not os.path.isabs(counts_path):
            counts_path = os.path.join(current_dir, counts_path)

    if count_dict_file_name is not None and os.path.exists(counts_path):
        # Reuse path: counts already cached from an earlier run. Skip the QPU.
        logger.info(f"Skipping sampler, loading counts dict from file: {counts_path}")
        with open(counts_path, "r") as file:
            count_dict_string = file.read().replace("\n", "")
        counts_dict = json.loads(count_dict_string.replace("'", '"'))
        waiting_qpu_time = 0
        executing_qpu_time = 0
    else:
        # Sampling path: no cached file (or caching disabled). Submit the LUCJ job.
        logger.info("Submitting sampler job")
        job = sampler.run([transpiled])
        logger.info(f"Job ID: {job.job_id()}")
        logger.info(f"Job Status: {job.status()}")

        start_waiting_qpu = time.time()
        while job.status() == "QUEUED":
            update_status(Job.WAITING_QPU)
            time.sleep(5)

        end_waiting_qpu = time.time()
        update_status(Job.EXECUTING_QPU)

        # Wait until job is complete
        result = job.result()
        end_executing_qpu = time.time()

        pub_result = result[0]
        counts_dict = pub_result.data.meas.get_counts()

        waiting_qpu_time = end_waiting_qpu - start_waiting_qpu
        executing_qpu_time = end_executing_qpu - end_waiting_qpu

        # Cache the sampled counts for later runs (dict repr, matching the reuse
        # branch's parser). A write failure is non-fatal: counts are already known.
        if count_dict_file_name is not None:
            try:
                serializable = {str(k): int(v) for k, v in counts_dict.items()}
                with open(counts_path, "w") as file:
                    file.write(repr(serializable))
                logger.info(f"Wrote {len(serializable)} bitstrings to counts cache: {counts_path}")
            except OSError as exc:
                logger.warning(f"Could not write counts cache to {counts_path}: {exc}")

    # --
    # Step 4: Post-process

    start_pp = time.time()
    update_status(Job.POST_PROCESSING)

    # SQD-PCM section
    start = time.time()

    # Orbitals, electron, and spin initialization
    num_orbitals = ncas
    if myavas is not None:
        num_elec_a = num_elec_b = int(nelecas / 2)
    else:
        num_elec_a, num_elec_b = nelecas
    spin_sq = input_spin

    # Convert counts into bitstring and probability arrays
    bitstring_matrix_full, probs_arr_full = counts_to_arrays(counts_dict)

    # Independent, CPU-bound per-batch eigensolvers, run one-per-process across the
    # profile's cores (replaces the Ray @distribute_task/get fan-out, which Fleets
    # cannot use). Size from sched_getaffinity (the cgroup quota), not cpu_count
    # (the whole node); fall back to cpu_count off Linux.
    try:
        available_cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        available_cpus = os.cpu_count() or 1
    max_workers = min(n_batches, available_cpus)

    # Threads per worker, set in the env before the (spawned) workers import numpy.
    # Auto: ~2 threads per worker's core share (mild oversubscription, since the
    # solve is only partly BLAS-bound), capped near 2x cores.
    if blas_threads_per_worker is not None:
        threads_per_worker = max(1, int(blas_threads_per_worker))
    else:
        threads_per_worker = max(1, (2 * available_cpus) // max_workers)
    for _tv in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[_tv] = str(threads_per_worker)
    logger.info(
        f"Worker BLAS threads: {threads_per_worker} "
        f"(available_cpus={available_cpus}, max_workers={max_workers})"
    )

    # Start workers with "spawn", not the Linux default "fork". By this point the
    # parent has imported PySCF and initialized OpenBLAS/OpenMP (and the openmpi
    # library the fleet image loads). Forking a process that already holds native
    # thread-pool / MPI locks gives the child an inherited-but-orphaned lock, and
    # the worker's first BLAS/MPI call can then deadlock forever with no traceback
    # -- which presents exactly as a silent hang after the batches are dispatched.
    # A spawned worker starts a fresh interpreter that imports those libraries
    # cleanly, at the cost of re-importing per worker (acceptable next to a
    # multi-second solve). forkserver is used if spawn is somehow unavailable.
    try:
        mp_context = mp.get_context("spawn")
    except ValueError:
        mp_context = mp.get_context("forkserver")
    logger.info(
        f"Running {n_batches} batches across {max_workers} worker processes "
        f"(start method: {mp_context.get_start_method()})"
    )

    e_hist = np.zeros((iterations, n_batches))  # energy history
    s_hist = np.zeros((iterations, n_batches))  # spin history
    g_solv_hist = np.zeros((iterations, n_batches))  # g_solv history
    occupancy_hist = []
    avg_occupancy = None

    # Create the pool ONCE and reuse it across all S-CORE iterations. Since spawn
    # cold-imports PySCF per worker, a per-iteration pool would re-pay that import
    # `iterations` times; one warm pool pays it once.
    num_ran_iter = 0
    # Split post-processing time into worker startup / serial prep / parallel solve
    # (surfaced in the result metadata) rather than one opaque number.
    warmup_time = 0.0
    prep_time_total = 0.0
    solve_time_total = 0.0

    with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context) as executor:
        # Force every worker to start (and cold-import PySCF under spawn) up front,
        # and time it, so the startup cost is measured once here instead of hiding
        # inside the first iteration's solve time.
        start_warmup = time.time()
        list(executor.map(_worker_warmup, range(max_workers)))
        warmup_time = time.time() - start_warmup
        logger.info(f"Worker pool warmup ({max_workers} workers): {warmup_time:.1f} s")

        for i in range(iterations):
            iter_start = time.time()
            logger.info(f"Starting configuration recovery iteration {i}")
            # On the first iteration, we have no orbital occupancy information from the
            # solver, so we begin with the full set of noisy configurations.
            if avg_occupancy is None:
                bs_mat_tmp = bitstring_matrix_full
                probs_arr_tmp = probs_arr_full

            # If we have average orbital occupancy information, we use it to refine the full
            # set of noisy configurations
            else:
                bs_mat_tmp, probs_arr_tmp = recover_configurations(
                    bitstring_matrix_full, probs_arr_full, avg_occupancy, num_elec_a, num_elec_b
                )

            # Post-select to remove configurations with incorrect hamming weight
            # (important on iteration 0, where no config recovery was performed yet),
            # then draw the batches of subsamples from what survives.
            #
            # This replaces the single ``postselect_and_subsample`` call, deprecated
            # in qiskit-addon-sqd 0.12.0, with its two successor functions:
            # ``postselect_by_hamming_right_and_left`` (returns the filtered matrix
            # and renormalized probabilities) feeding ``subsample``.
            bs_mat_ps, probs_arr_ps = postselect_by_hamming_right_and_left(
                bs_mat_tmp,
                probs_arr_tmp,
                hamming_right=num_elec_a,
                hamming_left=num_elec_b,
            )
            batches = subsample(
                bs_mat_ps,
                probs_arr_ps,
                samples_per_batch=samples_per_batch,
                num_batches=n_batches,
            )

            # Run the per-batch eigenstate solvers in parallel across worker processes.
            e_tmp = np.zeros(n_batches)
            s_tmp = np.zeros(n_batches)
            g_solvs_tmp = np.zeros(n_batches)
            occs_tmp = []
            coeffs = []

            for j in range(n_batches):
                strs_a, strs_b = bitstring_matrix_to_ci_strs(batches[j])
                logger.info(f"Batch {j} subspace dimension: {len(strs_a) * len(strs_b)}")

            # Everything above in this iteration (config recovery + postselect +
            # subsample) is serial prep that does not scale with cores; time it
            # separately from the parallel solve below.
            prep_time = time.time() - iter_start
            prep_time_total += prep_time
            start_solve = time.time()

            # Submit all batches and collect via as_completed (not executor.map) so
            # each batch logs as it finishes (progress vs. hang is visible) and a dead
            # worker raises via future.result() instead of hanging. res[j] is filled by
            # index to keep batch order, as Ray's get did.
            res = [None] * n_batches
            future_to_idx = {
                executor.submit(
                    _solve_solvent_worker,
                    (
                        batches[j],
                        myeps,
                        mymethod,
                        myavas,
                        num_orbitals,
                        spin_sq,
                        max_davidson_cycles,
                        checkpoint_file_name,
                    ),
                ): j
                for j in range(n_batches)
            }
            n_done = 0
            for future in as_completed(future_to_idx):
                j = future_to_idx[future]
                res[j] = future.result()  # re-raises any worker exception here
                n_done += 1
                logger.info(f"Batch {j} solved ({n_done}/{n_batches} complete)")

            solve_time = time.time() - start_solve
            solve_time_total += solve_time
            logger.info(
                f"Iteration {i} timing: prep {prep_time:.1f} s, "
                f"parallel solve {solve_time:.1f} s"
            )

            for j in range(n_batches):
                energy_sci, coeffs_sci, avg_occs, spin, g_solv = res[j]
                e_tmp[j] = energy_sci
                s_tmp[j] = spin
                g_solvs_tmp[j] = g_solv
                occs_tmp.append(avg_occs)
                coeffs.append(coeffs_sci)

            # Combine batch results
            avg_occupancy = tuple(np.mean(occs_tmp, axis=0))

            # Track optimization history
            e_hist[i, :] = e_tmp
            s_hist[i, :] = s_tmp
            g_solv_hist[i, :] = g_solvs_tmp
            occupancy_hist.append(avg_occupancy)

            lowest_e_batch_index = np.argmin(e_hist[i, :])

            logger.info(f"Lowest energy batch: {lowest_e_batch_index}")
            logger.info(f"Lowest energy value: {np.min(e_hist[i, :])}")
            logger.info(f"Corresponding g_solv value: {g_solv_hist[i, lowest_e_batch_index]}")
            logger.info("-----------------------------------")
            num_ran_iter += 1

    end_pp = time.time()
    end = time.time()
    duration = end - start
    logger.info(f"SCI_solver totally takes: {duration} seconds")

    metadata = {
        "resources_usage": {
            "RUNNING: MAPPING": {
                "CPU_TIME": end_mapping - start_mapping,
            },
            "RUNNING: OPTIMIZING_FOR_HARDWARE": {
                "CPU_TIME": end_optimizing - start_optimizing,
            },
            "RUNNING: WAITING_FOR_QPU": {
                "CPU_TIME": waiting_qpu_time,
            },
            "RUNNING: EXECUTING_QPU": {
                "QPU_TIME": executing_qpu_time,
            },
            "RUNNING: POST_PROCESSING": {
                "CPU_TIME": end_pp - start_pp,
            },
        },
        # Breakdown of the post-processing stage so the wall-clock can be
        # attributed to worker startup vs. serial prep (config recovery +
        # subsampling, which does not scale with cores) vs. the parallel solve.
        # Useful when comparing the process-pool runtime against the Ray baseline
        # or across compute profiles: solve_wall_time is the part a bigger profile
        # actually reduces.
        "post_processing_breakdown": {
            "worker_warmup_time": warmup_time,
            "serial_prep_time": prep_time_total,
            "parallel_solve_time": solve_time_total,
            "max_workers": max_workers,
            "available_cpus": available_cpus,
            "blas_threads_per_worker": threads_per_worker,
            "start_method": mp_context.get_start_method(),
        },
        "num_iterations_executed": num_ran_iter,
    }

    output = {
        "total_energy_hist": e_hist,
        "spin_squared_value_hist": s_hist,
        "solvation_free_energy_hist": g_solv_hist,
        "occupancy_hist": occupancy_hist,
        "lowest_energy_batch": lowest_e_batch_index,
        "lowest_energy_value": np.min(e_hist[i, :]),
        "solvation_free_energy": g_solv_hist[i, lowest_e_batch_index],
        "sci_solver_total_duration": duration,
        "metadata": metadata,
    }

    return output


# This is the section where `run_function` is called, it's boilerplate code and can be used
# without customization.
if __name__ == "__main__":

    # Use serverless helper function to extract input arguments,
    input_args = get_arguments()

    try:
        if input_args.pop("use_fake_backend", True):
            from qiskit_ibm_runtime.fake_provider import FakeHanoiV2  # pylint: disable=import-outside-toplevel

            input_args["testing_backend"] = FakeHanoiV2()
            input_args["count_dict_file_name"] = "water_mini_count_dict.txt"
        elif not input_args.get("backend_name"):
            raise ValueError("backend_name is required when use_fake_backend is false")
        else:
            input_args.pop("count_dict_file_name", None)
        func_result = run_function(**input_args)
        # Use serverless function to save the results that
        # will be returned in the job.
        save_result(func_result)
    except Exception:
        save_result(traceback.format_exc())
        raise

    sys.exit(0)
