import os
import numpy as np

# for analysis NPL developed packages
import punpy
import matheo.band_integration as band_integration

# zhangWrapper
import collections
import ZhangRho

# M99 Rho
from HDFRoot import HDFRoot
from Utilities import Utilities
from ConfigFile import ConfigFile
from RhoCorrections import RhoCorrections

# TODO remove this part and properly address the warning
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


class Propagate:
    """
    Class to contain all uncertainty analysis to be used in HyperInSPACE

    used to contain mesurement functions as well as functions to appy uncertainty analsys to HyperInSPACE products:
    inputs, processes and derrivatives.

    path: Str - output path for results to be written too
    M: Int - number of monte carlo draws
    cores: Int - punpy parallel_cores option (see documentation) Set None to ignore, 1 is default.
    """
    MCP: punpy.MCPropagation
    corr_fp: str = os.path.join(os.path.dirname(__file__), os.path.pardir, 'Data', 'correlation_mats.csv')
    corr_matrices: dict = {}

    def __init__(self, M: int = 10000, cores: int = 1):
        if isinstance(cores, int):
            self.MCP = punpy.MCPropagation(M, parallel_cores=cores)
        else:
            self.MCP = punpy.MCPropagation(M)

        if not self._read_correlation():
            msg = "unable to read correlation matrices, please ensure the file is in the correct format"
            Utilities.writeLogFile(msg)
            print(msg)

    # Main functions
    def propagate_Instrument_Uncertainty(self, mean_vals, uncertainties):
        """
        ESLIGHT, ESDARK, LILIGHT, LIDARK, LTLIGHT, LTDARK, ESCal, LICal, LTCal, ESStab, LIStab, LTStab,
        ESLin, LILin, LTLin, ESStray, LIStray, LTStray, EST, LIT, LTT, LIPol, LTPol, ESCos
        :Return: absolute uncertainty [es, li, lt] relative uncertainty [es, li, lt]
        """
        sensor = self.instruments(*mean_vals)

        if 'RAD' not in self.corr_matrices:
            msg = "could not find correlation matrix for instrument uncertainties"
            return False

        corr_list = ['rand', 'rand', 'rand', 'rand', 'rand', 'rand', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst',
                     'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst']

        unc, _, corr = self.MCP.propagate_random(self.instruments, mean_vals, uncertainties,
                                                 corr_between=self.corr_matrices['RAD'], corr_x=corr_list,
                                                 output_vars=3, return_corr=True)

        # separate uncertainties and sensor values from their lists - for clarity
        Es_unc, Li_unc, Lt_unc = [unc[i] for i in range(3)]
        es, li, lt = [sensor[i] for i in range(3)]

        Es_rel = []; Li_rel = []; Lt_rel = []
        for i in range(len(lt)):
            if es[i] == 0:
                Es_rel.append(Es_unc[i])
            else:
                Es_rel.append((Es_unc[i] * 1e10) / (es[i] * 1e10))
            if li[i] == 0:
                Li_rel.append(Li_unc[i])
            else:
                Li_rel.append((Li_unc[i] * 1e10) / (li[i] * 1e10))
            if lt[i] == 0:
                Lt_rel.append(Lt_unc[i])
            else:
                Lt_rel.append((Lt_unc[i] * 1e10) / (lt[i] * 1e10))

        # correlation matrix   1.0    es/li  es/lt
        #                      es/li  1.0    li/lt
        #                      es/lt  li/lt  1.0

        self.corr_matrices['Es'] = corr[:, 0]
        self.corr_matrices['Li'] = corr[:, 1]
        self.corr_matrices['Lt'] = corr[:, 2]

        if not self._write_correlation():
            msg = 'could not write out instrument correlation from level 1b'
            Utilities.writeLogFile(msg)
            print(msg)

        return Es_unc, Li_unc, Lt_unc, Es_rel, Li_rel, Lt_rel

    def Propagate_Lw(self, varlist, ulist):
        """ will be replaced in the near future """
        corr_matrix = np.array([
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
            ])

        lw = self.Lw(*varlist)
        unc = self.MCP.propagate_random(self.Lw, varlist, ulist, corr_between=corr_matrix)
        return (unc * 1e10) / (lw * 1e10), unc, lw

    # def Propagate_RRS_cal(self, varlist: list, ulist: list) -> dict:
    #     """lt, rhoVec, li, es, c1, c2, c3, clin1, clin2, clin3, cstab1, cstab2, cstab3, cstray1, cstray2, cstray3,
    #             cT1, cT2, cT3, cpol1, cpol2, ccos
    #         will be replaced in the near future - for pixel by pixel method """
    #     corr_matrix = np.array([
    #         [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
    #         [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    #         ], dtype=np.float)
    #
    #     unc = self.MCP.propagate_random(self.RRS, varlist, ulist, corr_between=corr_matrix)
    #     rrs = self.RRS(*varlist)
    #
    #     return (unc * 1E9) / (rrs * 1E9)  # replace with just 'unc' for absolute uncertainty

    def Propagate_RRS(self, mean_vals: list, uncertainties: list) -> dict:
        """lt, rhoVec, li, es, c1, c2, c3, clin1, clin2, clin3, cstab1, cstab2, cstab3, cstray1, cstray2, cstray3,
                cT1, cT2, cT3, cpol1, cpol2, ccos
            will be replaced in the near future - for pixel by pixel method """
        corr_matrix = np.array([
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            ], dtype=np.float)
        corr_list = ['rand', 'syst', 'rand', 'rand', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst',
                     'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst', 'syst']

        rrs = np.array(self.RRS(*mean_vals))
        unc = self.MCP.propagate_standard(self.RRS, mean_vals, uncertainties, corr_between=corr_matrix, corr_x=corr_list)
        return (unc * 1E9) / (rrs * 1E9), unc, rrs  # replace with just 'unc' for absolute uncertainty

    def band_Conv_Uncertainty(self, mean_vals, uncertainties):
        """Hyper_Rrs, wvl, Band cetral wavelengths, Band width - only works for sentinel 3A - OLCI
            :return: relative Rrs uncertainty per spectral band"""
        rad_band = self.band_Conv_Sensor(*mean_vals)
        return (self.MCP.propagate_standard(self.band_Conv_Sensor, mean_vals, uncertainties, corr_x=['rand', None]) * 1e9) / (rad_band * 1e9)

    # Rho propagation methods
    def M99_Rho_Uncertainty(self, varlist, ulist):
        return self.MCP.propagate_random(self.rhoM99, varlist, ulist, corr_x=["rand", "rand", "rand"])

    # Measurement Functions
    @staticmethod
    def instruments(ESLIGHT, ESDARK, LILIGHT, LIDARK, LTLIGHT, LTDARK, ESCal, LICal, LTCal, ESStab, LIStab, LTStab,
                    ESLin, LILin, LTLin, ESStray, LIStray, LTStray, EST, LIT, LTT, LIPol, LTPol, ESCos):
        """Instrument specific uncertainties measurement function"""
        return np.array((ESLIGHT - ESDARK)*ESCal*ESStab*ESLin*ESStray*EST*ESCos), \
               np.array((LILIGHT - LIDARK)*LICal*LIStab*LILin*LIStray*LIT*LIPol), \
               np.array((LTLIGHT - LTDARK)*LTCal*LTStab*LTLin*LTStray*LTT*LTPol)

    @staticmethod
    def band_Conv_Sensor(Hyperspec, Wavelengths):  #, platform_name: str = None, sensor_name: str = None):
        """ band convolution of Rrs"""
        rad_band, band_centres = band_integration.spectral_band_int_sensor(d=Hyperspec, wl=Wavelengths,
                                                                            platform_name="Sentinel-3A",
                                                                            sensor_name="olci", u_d=None)
        return rad_band

    @staticmethod
    def Lw(lt, rhoVec, li, c2, c3, clin2, clin3, cstab2, cstab3, cstray2, cstray3, cT2, cT3, cpol1, cpol2):
        Li = li * c2 * clin2 * cstab2 * cstray2 * cT2 * cpol1
        Lt = lt * c3 * clin3 * cstab3 * cstray3 * cT3 * cpol2
        return Lt - (Li * rhoVec)

    @staticmethod
    def RRS(lt, rhoVec, li, es, c1, c2, c3, clin1, clin2, clin3, cstab1, cstab2, cstab3, cstray1, cstray2, cstray3,
                cT1, cT2, cT3, cpol1, cpol2, ccos):
        lw = ((lt*c3*clin3*cstab3*cstray3*cT3*cpol2) - (rhoVec*(li*c2*cstab2*clin2*cstray2*cT2*cpol1)))
        return lw/(es*c1*cstab1*clin1*cstray1*cT1*ccos)

    @staticmethod
    def rhoM99(windSpeedMean, SZAMean, relAzMean):
        theta = 40  # viewing zenith angle
        winds = np.arange(0, 14 + 1, 2)  # 0:2:14
        szas = np.arange(0, 80 + 1, 10)  # 0:10:80
        phiViews = np.arange(0, 180 + 1, 15)  # 0:15:180 # phiView is relAz

        # Find the nearest values in the LUT
        wind_idx = Utilities.find_nearest(winds, windSpeedMean)
        wind = winds[wind_idx]
        sza_idx = Utilities.find_nearest(szas, SZAMean)
        sza = szas[sza_idx]
        relAz_idx = Utilities.find_nearest(phiViews, relAzMean)
        relAz = phiViews[relAz_idx]

        # load in the LUT HDF file
        inFilePath = os.path.join(ConfigFile.fpHySP, 'Data', 'rhoTable_AO1999.hdf')
        lut = HDFRoot.readHDF5(inFilePath)
        lutData = lut.groups[0].datasets['LUT'].data

        # convert to a 2D array
        lut = np.array(lutData.tolist())

        # match to the row
        row = lut[(lut[:, 0] == wind) & (lut[:, 1] == sza) & \
                  (lut[:, 2] == theta) & (lut[:, 4] == relAz)]

        rhoScalar = row[0][5]

        return rhoScalar

    def zhangWrapper(self, windSpeedMean, AOD, cloud, sza, wTemp, sal, relAz, waveBands):
        '''
        NOTE: Be sure calls to zhangWrapper to send abs(relAz) if derived from data - DA
        '''
        print(f"CALL TO WRAPPER: {self.i}")

        # === environmental conditions during experiment ===
        env = collections.OrderedDict()
        env['wind'] = windSpeedMean
        env['od'] = AOD
        env['C'] = cloud  # Not used
        env['zen_sun'] = sza
        env['wtem'] = wTemp
        env['sal'] = sal

        # === The sensor ===
        sensor = collections.OrderedDict()
        sensor['ang'] = [40, 180 - relAz]  # relAz should vary from about 90-135
        sensor['wv'] = waveBands

        self.i += 1

        rhoStructure = ZhangRho.Main(env, sensor)

        return rhoStructure['ρ']

    # Utilities
    def _read_correlation(self):
        end_cond = False
        with open(self.corr_fp, 'r') as f:
            while True:
                line = Utilities.getline(f, '\n')
                if line:
                    end_cond = False
                    if line.startswith('['):
                        if 'END' not in line:
                            new_corr_matrix = []
                            key = line[1:-1]
                        else:
                            self.corr_matrices[key] = np.array(new_corr_matrix)  # add matrix to the dictionary
                            del new_corr_matrix
                            key = None
                    else:
                        new_corr_matrix.append(np.array([float(i) for i in line.split(',') if i]))  # add the line to the list
                else:
                    if end_cond:
                        break
                    else:
                        end_cond = True
        return True

    def _write_correlation(self):
        with open(self.corr_fp, 'w') as f:
            for key in self.corr_matrices:
                f.write(f"[{key}]\n")
                for item in self.corr_matrices[key]:
                    if isinstance(item, np.ndarray):
                        f.write(f"{','.join([str(i) for i in item])}\n")
                        newline = False
                    else:
                        f.write(f"{item},")
                        newline = True
                if newline:
                    f.write("\n")
                f.write(f"[END {key}]\n")
        return True
