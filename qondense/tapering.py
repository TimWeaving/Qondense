from qondense.S3_projection import S3_projection
from qondense.utils.QubitOp import QubitOp
from qondense.utils.operator_toolkit import exact_gs_energy, measure_operator
from qondense.utils.symplectic_toolkit import *
from itertools import product
from typing import Dict
import numpy as np

class tapering(S3_projection):
    """ Class for performing qubit tapering as per https://arxiv.org/abs/1701.08213.
    Reduces the number of qubits in the problem whilst preserving its energy spectrum by:

    1. identifying a symmetry of the Hamiltonian,
    2. finding an independent basis therein,
    3. rotating each basis operator onto a single Pauli X, 
    4. dropping the corresponding qubits from the Hamiltonian whilst
    5. fixing the +/-1 eigenvalues

    Steps 1-2 are handled in this class whereas we defer to the parent S3_projection for 3-5.

    """
    def __init__(self, 
                hamiltonian: Dict[str, float],
                ref_state: List[int],
                target_sqp: str = 'X'):
        """ Input a Hamiltonian in the dictionary representation...
        ... and some reference state such as Hartree-Fock, e.g. |0...01...1>
        There is freedom over the choice of single Pauli operator we wish to rotate onto, 
        however this is set to X by default (in line with the original tapering paper).
        """
        self.hamiltonian  = QubitOp(hamiltonian)
        self.n_qubits      = self.hamiltonian.n_qubits
        assert(len(ref_state)==self.n_qubits)
        self.ref_state    = ref_state
        self.target_sqp = target_sqp
        self.symmetry_ops = self.identify_symmetry_generators()
        self.symmetry_sec = self.identify_symmetry_sector()
        self.n_taper      = len(self.symmetry_ops)
        # initialize the S3_projection class
        super().__init__(
            stabilizers = self.symmetry_ops, 
            eigenvalues = self.symmetry_sec, 
            target_sqp= self.target_sqp
        )


    def identify_symmetry_generators(self):
        """ Find an independent basis for the Hamiltonian symmetry
        This is carried out in the symplectic representation.
        """
        # swap order of XZ blocks in symplectic matrix to ZX
        ZX_symp = self.hamiltonian.swap_XZ_blocks().toarray()
        reduced = gf2_gaus_elim(ZX_symp)
        kernel  = gf2_basis_for_gf2_rref(reduced)

        return [pauli_from_symplectic(row) for row in kernel]


    def identify_symmetry_sector(self):
        """ Given the specified reference state, determine the
        correspinding sector by measuring the symmetry generators
        """
        sector = [measure_operator(pauli, self.ref_state) 
                    for pauli in self.symmetry_ops]
        return sector


    def update_S3_projection(self,symmetry_sector):
        """ Exists so that we may explore different sectors
        other than that obtained from the reference state
        """
        super().__init__(
            stabilizers = self.symmetry_ops, 
            eigenvalues = symmetry_sector, 
            target_sqp= self.target_sqp
        )


    def taper_it(self, operator:QubitOp = None)->QubitOp:
        """ Finally, once the symmetry generators and sector have been
        identified, we may perform a projection onto the corresponding
        stabilizer subspace via the parent S3_projection class.

        This method allows one to input an operator other than the
        Hamiltonian itself to be tapered consistently with the Hamiltonian
        symmetry. This is especially useful when considering an Ansatz
        defined over the full system that one wishes to restrict to the
        same stabilizer subspace for use in VQE, for example.
        """                     
        if operator is None:
            operator = self.hamiltonian
        elif operator is not None and type(operator)==dict:
            operator = QubitOp(operator)
        
        tapered_operator = self.perform_projection(operator)
        
        return tapered_operator


    def taper_ref_state(self) -> List[int]:
        """ taper the reference state by dropping the qubit positions
        projected during the perform_projection method
        """
        # require perform_projection to have been called so that 
        # stab_index_eigval is defined:
        self.perform_projection(self.hamiltonian)
        taper_qubits= list(self.stab_index_eigval.keys())
        tapered_ref_state = [bit for index,bit in enumerate(self.ref_state) 
                                    if index not in taper_qubits]
        return tapered_ref_state
        
        
    def search_all_sectors(self):
        """ Hartree-Fock does not always identify the sector in which 
        the correct ground state energy resides... for this reason,
        this method searches through every sector and calculates the
        ground state energy in each to find the correct one.
        
        *** very much NOT scalable!
        """
        tapered_ham = []
        if self.n_qubits < 5:
            matrix_type='dense'
        else:
            matrix_type='sparse'
        
        all_sectors = product([+1,-1], repeat=self.n_taper)
        for sector in all_sectors:
            self.update_S3_projection(sector)
            hamtap = self.taper_it()._dict()
            energy = exact_gs_energy(hamtap, matrix_type)[0]
            tapered_ham.append(
                (
                    sector,
                    energy,
                    hamtap
                )
            )
        
        return sorted(tapered_ham, key=lambda x:x[1])