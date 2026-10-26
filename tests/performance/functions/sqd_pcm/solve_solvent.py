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

"""Functions for the study of fermionic systems."""

from __future__ import annotations

import warnings

import numpy as np

# DSK Add imports needed for CASCI wrapper
from pyscf import ao2mo, scf, fci
from pyscf.mcscf import avas, casci
from pyscf.solvent import pcm
from pyscf.lib import chkfile, logger

from qiskit_addon_sqd.fermion import (
    SCIState,
    bitstring_matrix_to_ci_strs,
    _check_ci_strs,
)
from importlib_metadata import version

# DSK Below is the modified CASCI kernel compatible with SQD.
# It utilizes the "fci.selected_ci.kernel_fixed_space"
# as well as enables passing the "batch" and "max_davidson"
# input arguments from "solve_solvent".
# The "batch" contains the CI addresses corresponding to subspaces
# derived from LUCJ and S-CORE calculations.
# The "max_davidson" controls the maximum number of cycles of Davidson's algorithm.


# pylint: disable = unused-argument
def kernel(casci_object, mo_coeff=None, ci0=None, verbose=logger.NOTE, envs=None):
    """CASCI solver compatible with SQD.

    Args:
        casci_object: CASCI or CASSCF object.
        In case of SQD, only CASCI instance is currently incorporated.

        mo_coeff : ndarray
            orbitals to construct active space Hamiltonian.
            In context of SQD, these are either AVAS mo_coeff
            or all of the MOs (with option to exclude core MOs).

        ci0 : ndarray or custom types FCI solver initial guess.
            For SQD the usage of ci0 was not tested.

            For external FCI-like solvers, it can be
            overloaded different data type. For example, in the state-average
            FCI solver, ci0 is a list of ndarray. In other solvers such as
            DMRGCI solver, SHCI solver, ci0 are custom types.

    kwargs:
        envs: dict
            In case of SQD this option was not explored,
            but in principle this can facilitate the incorporation of the external solvers.

            The variable envs is created (for PR 807) to passes MCSCF runtime
            environment variables to SHCI solver. For solvers which do not
            need this parameter, a kwargs should be created in kernel method
            and "envs" pop in kernel function.
    """
    if mo_coeff is None:
        mo_coeff = casci_object.mo_coeff
    if ci0 is None:
        ci0 = casci_object.ci

    log = logger.new_logger(casci_object, verbose)
    t0 = (logger.process_clock(), logger.perf_counter())
    log.debug("Start CASCI")

    ncas = casci_object.ncas
    nelecas = casci_object.nelecas

    # The start of SQD version of kernel
    # DSK add the read of configurations for batch
    ci_strs_sqd = casci_object.batch

    # DSK add the input for the maximum number of cycles of Davidson's algorithm
    max_davidson = casci_object.max_davidson

    # DSK add electron up and down count and norb = ncas
    n_up = nelecas[0]
    n_dn = nelecas[1]
    norb = ncas

    # DSK Eignestate solver info
    sqd_verbose = verbose

    # DSK ERI read
    eri_cas = ao2mo.restore(1, casci_object.get_h2eff(), casci_object.ncas)
    t1 = log.timer("integral transformation to CAS space", *t0)

    # DSK 1e integrals
    h1eff, energy_core = casci_object.get_h1eff()
    log.debug("core energy = %.15g", energy_core)
    t1 = log.timer("effective h1e in CAS space", *t1)

    if h1eff.shape[0] != ncas:
        raise RuntimeError(
            "Active space size error. nmo=%d ncore=%d ncas=%d"  # pylint: disable=consider-using-f-string
            % (mo_coeff.shape[1], casci_object.ncore, ncas)
        )

    # DSK fcisolver needs to be defined in accordance with SQD
    # in this software stack it is done in the "solve_solvent" portion of the code.
    myci = casci_object.fcisolver
    e_cas, sqdvec = fci.selected_ci.kernel_fixed_space(
        myci,
        h1eff,
        eri_cas,
        norb,
        (n_up, n_dn),
        ci_strs=ci_strs_sqd,
        verbose=sqd_verbose,
        max_cycle=max_davidson,
    )

    # DSK fcivec is the general name for CI vector assinged by PySCF.
    # Depending on type of solver it is either FCI or SCI vector.
    # In case of sqd we can call it "sqdvec" for clarity.
    # Nonetheless, for further processing PySCF expects
    # this data structure to be called fcivec, regardless of the used solver.

    fcivec = sqdvec

    t1 = log.timer("CI solver", *t1)
    e_tot = energy_core + e_cas

    # Returns either standard CASCI data or SQD data. Return depends on "sqd_run" True/False.
    return e_tot, e_cas, fcivec


# Replace standard CASCI kernel with the SQD-compatible CASCI kernel defined above
casci.kernel = kernel


def solve_solvent(
    bitstring_matrix: tuple[np.ndarray, np.ndarray] | np.ndarray,
    /,
    myeps: float,
    mysolvmethod: str,
    myavas: list,
    num_orbitals: int,
    *,
    spin_sq: int | None = None,
    max_davidson: int = 100,
    verbose: int | None = 0,
    checkpoint_file: str,
) -> tuple[float, SCIState, list[np.ndarray], float]:
    """Approximate the ground state given molecular integrals and a set of electronic configurations.

    Args:
        bitstring_matrix: A set of configurations defining the subspace onto which the Hamiltonian
            will be projected and diagonalized. This is a 2D array of ``bool`` representations of bit
            values such that each row represents a single bitstring. The spin-up configurations
            should be specified by column indices in range ``(N, N/2]``, and the spin-down
            configurations should be specified by column indices in range ``(N/2, 0]``, where ``N``
            is the number of qubits.

            (DEPRECATED) The configurations may also be specified by a length-2 tuple of sorted 1D
            arrays containing unsigned integer representations of the determinants. The two lists
            should represent the spin-up and spin-down orbitals, respectively.

        To build PCM model PySCF needs the structure of the molecule. Hence, the electron integrals
        (hcore and eri) are not enough to form IEF-PCM simulation. Intead the "start.chk" file is used.
        This workflow also requires additional information about solute and solvent,
        which is reflected by additional arguments below

        myeps: Dielectric parameter of the solvent.
        mysolvmethod: Solvent model, which can be IEF-PCM, COSMO, C-PCM, SS(V)PE,
               see https://manual.q-chem.com/5.4/topic_pcm-em.html
               At the moment only IEF-PCM was tested.
               In principle two other models from PySCF "solvent" module can be used as well,
               namely SMD and polarizable embedding (PE).
               The SMD and PE were not tested yet and their usage requires addition of more
               input arguments for "solve_solvent".
        myavas: This argument allows user to select active space in solute with AVAS.
                The corresponding list should include target atomic orbitals.
                If myavas=None, then active space selected based on number of orbitals
                derived from ci_strs.
                It is assumed that if myavas=None, then the target calculation is either
                a) corresponds to full basis case.
                b) close to full basis case and only few core orbitals are excluded.
        num_orbitals: Number of orbitals, which is essential when myavas = None.
                In AVAS case number of orbitals and electrons is derived by AVAS procedure itself.
        spin_sq: Target value for the total spin squared for the ground state.
            If ``None``, no spin will be imposed.
        max_davidson: The maximum number of cycles of Davidson's algorithm
        verbose: A verbosity level between 0 and 10
        checkpoint_file: Name of the checkpoint file

        NOTE: For now open shell functionality is not supported in SQD PCM calculations.
              Hence, at the moment solve_solvent does not include open_shell as one of the arguments.

    Returns:
        - Minimum energy from SCI calculation
        - The SCI ground state
        - Average occupancy of the alpha and beta orbitals, respectively
        - Expectation value of spin-squared
        - Solvation free energy

    """
    # Unlike the "solve_fermion", the "solve_solvent" utilizes the "checkpoint" file to
    # get the starting HF information, which means that "solve_solvent" does not accept
    # "hcore" and "eri" as the input arguments.
    # Instead "hcore" and "eri" are generated inside of the custom SQD-compatible
    # CASCI kernel (defined above).
    # The generation of "hcore" and "eri" is based on the information from "checkpoint" file
    # as well as "myavas" and "num_orbitals" input arguments.

    # DSK this part handles addresses and is identical to "solve_fermion"
    if isinstance(bitstring_matrix, tuple):
        warnings.warn(
            "Passing the input determinants as integers is deprecated. "
            "Users should instead pass a bitstring matrix defining the subspace.",
            DeprecationWarning,
            stacklevel=2,
        )
        ci_strs = bitstring_matrix
    else:
        # This will become the default code path after the deprecation period.
        ci_strs = bitstring_matrix_to_ci_strs(bitstring_matrix, open_shell=False)
    ci_strs = _check_ci_strs(ci_strs)

    num_up = format(ci_strs[0][0], "b").count("1")
    num_dn = format(ci_strs[1][0], "b").count("1")

    # DSK assign verbosity
    verbose_ci = verbose

    # DSK add information about solute and solvent.
    # Since PCM model needs the information about the structure of the molecule
    # one cannot use only FCIDUMP. Instead converged HF data can be passed from "checkpoint" file
    # along with "mol" object containing the geometry and other information about the solute.

    ############################################
    # This section is specific to "solve_solvent" and is not present in "solve_fermion".
    # In case of "solve_fermion" the "eri" and "hcore" are passed directly to
    # "fci.selected_ci.kernel_fixed_space".
    # In case of "solve_solvent" the incorporation of the polarizable continuum model
    # requires utilization of "CASCI.with_solvent"
    # data object from PySCF, where underlying CASCI.base_kernel has to be replaced
    # with SQD-compatible version.
    # Due to these differences in the implementation the "solve_solvent" recovers
    # the converged mean field results and "molecule" object from "checkpoint" file
    # (instead of using FCIDUMP),
    # followed by passing of solute, solvent, and active space information to "CASCI.with_solvent".
    # This includes the initiation of "mol", "cm", "mf", and "mc" data structures.

    mol = chkfile.load_mol(checkpoint_file)

    # DSK Initiation of the solvent model
    cm = pcm.PCM(mol)
    cm.eps = myeps  # solute eps value
    cm.method = mysolvmethod  # IEF-PCM, COSMO, C-PCM, SS(V)PE,
    # see https://manual.q-chem.com/5.4/topic_pcm-em.html

    # DSK Read-in converged RHF solution
    scf_result_dic = chkfile.load(checkpoint_file, "scf")
    mf = scf.RHF(mol).PCM(cm)
    mf.__dict__.update(scf_result_dic)

    # Identify the active space based on the user input of AVAS or number of orbitals and electrons
    if myavas is not None:
        orbs = myavas
        avas_obj = avas.AVAS(mf, orbs, with_iao=True)
        avas_obj.kernel()
        ncas, nelecas, _, _, _ = (
            avas_obj.ncas,
            avas_obj.nelecas,
            avas_obj.mo_coeff,
            avas_obj.occ_weights,
            avas_obj.vir_weights,
        )
    else:
        ncas = num_orbitals
        nelecas = (num_up, num_dn)

    # Initiate the "CASCI.with_solvent" object
    mc = casci.CASCI(mf, ncas=ncas, nelecas=nelecas).PCM(cm)
    # Replace mo_coeff with ones produced by AVAS if AVAS is utilized
    if myavas is not None:
        mc.mo_coeff = avas_obj.mo_coeff
    # Read-in the configuration interaction subspace derived from LUCJ and S-CORE
    mc.batch = ci_strs
    # Assign number of maxium Davidson steps
    mc.max_davidson = max_davidson

    ####### The defenition of "fcisolver" object is indetical to "solve_fermion" case ########
    myci = fci.selected_ci.SelectedCI()
    if spin_sq is not None:
        myci = fci.addons.fix_spin_(myci, ss=spin_sq)
    mc.fcisolver = myci
    mc.verbose = verbose_ci
    # Propagate the requested verbosity to the SelectedCI solver itself. Without
    # this it keeps PySCF's default level (NOTE), and its dump_flags() prints a
    # multi-line "inefficient dialect of Selected CI ... use Dice" banner via
    # logger.warn on every solve -- which, with one solver per batch per
    # iteration, floods the job logs. That message is advisory (SQD deliberately
    # uses this fixed-subspace solver), not an error, so we honor verbose_ci here
    # and it stays silent at the default verbose=0 while still being recoverable
    # by raising the verbosity.
    myci.verbose = verbose_ci
    #########################################################################################

    # Initiate the "CASCI.with_solvent" simulation with SQD-compatible based CASCI kernel.
    mc_result = mc.kernel()

    # Get data out of the "CASCI.with_solvent" object
    e_sci = mc_result[0]
    sci_vec = mc_result[2]
    # Here we get additional output comparing to "solve_fermion",
    # which is the solvation free energy (G_solv)
    g_solv = mc.with_solvent.e

    #####################################################
    # The remainder of the code in solve_solvent is nearly identical to solve_fermion code.

    # However, there are two exceptions in "solve_solvent":

    # 1) The dm2 is currently not computed, but can be included if needed
    # 2) e_sci is directly outputed as the result of CASCI.with_solvent object.

    # Hence, the two following lines of code are not present in "solve_solvent"
    # comparing to the "solve_fermion" code:

    # dm2 = myci.make_rdm2(sci_vec, norb, (num_up, num_dn))
    # e_sci = np.einsum("pr,pr->", dm1, hcore) + 0.5 * np.einsum("prqs,prqs->", dm2, eri)

    # Calculate the avg occupancy of each orbital
    dm1 = myci.make_rdm1s(sci_vec, ncas, (num_up, num_dn))
    avg_occupancy = [np.diagonal(dm1[0]), np.diagonal(dm1[1])]

    # Compute total spin
    spin_squared = myci.spin_square(sci_vec, ncas, (num_up, num_dn))[0]

    # Convert the PySCF SCIVector to internal format. We access a private field here,
    # so we assert that we expect the SCIVector output from kernel_fixed_space to
    # have its _strs field populated with alpha and beta strings.
    assert isinstance(sci_vec._strs[0], np.ndarray) and isinstance(sci_vec._strs[1], np.ndarray)
    assert sci_vec.shape == (len(sci_vec._strs[0]), len(sci_vec._strs[1]))
    if (
        int(version("qiskit_addon_sqd").split(".")[0]) == 0
        and int(version("qiskit_addon_sqd").split(".")[1]) < 11
    ):
        sci_state = SCIState(
            amplitudes=np.array(sci_vec),
            ci_strs_a=sci_vec._strs[0],
            ci_strs_b=sci_vec._strs[1],
        )
    else:
        sci_state = SCIState(
            amplitudes=np.array(sci_vec),
            ci_strs_a=sci_vec._strs[0],
            ci_strs_b=sci_vec._strs[1],
            norb=num_orbitals,
            nelec=(num_up, num_dn),
        )

    return e_sci, sci_state, avg_occupancy, spin_squared, g_solv
