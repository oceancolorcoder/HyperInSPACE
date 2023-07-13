# import python packages
import os
import numpy as np
import scipy as sp
import pandas as pd
import collections
from decimal import Decimal

# NPL packages
import punpy
import comet_maths as cm

# HCP files
import Utilities
from ConfigFile import ConfigFile
from ProcessL1b import ProcessL1b
from ProcessL1b_Interp import ProcessL1b_Interp
from Uncertainty_Analysis import Propagate
from MesurementFunctions import L1BMesurementFunctions as mf


class Instrument:
    """Base class for instrument uncertainty analysis"""

    def __init__(self):
        pass

    @staticmethod
    def lightDarkStats(grp, sensortype):
        pass

    def generateSensorStats(self, rawGroups):
        output = {}
        Start = {}
        End = {}
        types = ['ES', 'LI', 'LT']
        for sensortype in types:
            output[sensortype] = self.lightDarkStats(rawGroups[sensortype], sensortype)

            # generate common wavebands for interpolation
            wvls = np.asarray(output[sensortype]['wvl'], dtype=float)
            Start[sensortype] = np.ceil(wvls[0])
            End[sensortype] = np.floor(wvls[-1])

        start = max([Start[stype] for stype in types])
        end = min([End[stype] for stype in types])
        newWavebands = np.arange(start, end, float(ConfigFile.settings["fL1bInterpInterval"]))

        # interpolate to common wavebands
        for stype in types:
            wvls = np.asarray(output[stype]['wvl'], dtype=float)  # get sensor specific wavebands
            output[stype]['ave_Light'], _ = Instrument_Unc.interp_common_wvls(output[stype]['ave_Light'], wvls,
                                                                              newWavebands)
            output[stype]['std_Light'], _ = Instrument_Unc.interp_common_wvls(output[stype]['std_Light'], wvls,
                                                                              newWavebands)
            _, output[stype]['std_Signal'] = Instrument_Unc.interp_common_wvls(
                np.asarray(list(output[stype]['std_Signal'].values())),
                np.asarray(list(output[stype]['std_Signal'].keys()), dtype=float),
                newWavebands)
        return output

    ## Branch Processing
    @staticmethod
    def factory():
        pass

    @staticmethod
    def Default(node, stats):
        # read in uncertainties from HDFRoot and define propagate object
        uncGrp = node.getGroup("UNCERTAINTY_BUDGET")
        PropagateL1B = Propagate(M=100, cores=0)

        # define dictionaries for uncertainty components
        Cal = {}
        Coeff = {}
        cPol = {}
        cStray = {}
        Ct = {}
        cLin = {}
        cStab = {}

        # loop through instruments
        for sensor in ["ES", "LI", "LT"]:
            straylight = uncGrp.getDataset(f"{sensor}_STRAYDATA_CAL")
            straylight.datasetToColumns()
            cStray[sensor] = np.asarray(list(straylight.data[1]))

            linear = uncGrp.getDataset(sensor + "_NLDATA_CAL")
            linear.datasetToColumns()
            cLin[sensor] = np.asarray(list(linear.data[1]))

            stab = uncGrp.getDataset(sensor + "_STABDATA_CAL")
            stab.datasetToColumns()
            cStab[sensor] = np.asarray(list(stab.data[1]))

            radcal = uncGrp.getDataset(f"{sensor}_RADCAL_CAL")
            radcal.datasetToColumns()
            Coeff[sensor] = np.asarray(list(radcal.data[2]))
            Cal[sensor] = np.asarray(list(radcal.data[3]))

            pol = uncGrp.getDataset(sensor + "_POLDATA_CAL")
            pol.datasetToColumns()
            cPol[sensor] = np.asarray(list(pol.data[1]))

            # temp uncertainties calculated at L1AQC
            Temp = uncGrp.getDataset(sensor + "_TEMPDATA_CAL")
            Temp.datasetToColumns()
            Ct[sensor] = np.array(
                [Temp.columns[k][-1] for k in Temp.columns])  # last row of temp group has uncertainties

        ones = np.ones(len(Cal['ES']))  # to provide array of 1s with the correct shape

        # create lists containing mean values and their associated uncertainties (list order matters)
        mean_values = [stats['ES']['ave_Light'], ones*stats['ES']['ave_Dark'],
                       stats['LI']['ave_Light'], ones*stats['LI']['ave_Dark'],
                       stats['LT']['ave_Light'], ones*stats['LT']['ave_Dark'],
                       Coeff['ES'], Coeff['LI'], Coeff['LT'],
                       ones, ones, ones,
                       ones, ones, ones,
                       ones, ones, ones,
                       ones, ones, ones,
                       ones, ones, ones]

        uncertainty = [stats['ES']['std_Light'], ones*stats['ES']['std_Dark'],
                       stats['LI']['std_Light'], ones*stats['LI']['std_Dark'],
                       stats['LT']['std_Light'], ones*stats['LT']['std_Dark'],
                       Cal['ES']*Coeff['ES']/100, Cal['LI']*Coeff['LI']/100, Cal['LT']*Coeff['LT']/100,
                       cStab['ES'], cStab['LI'], cStab['LT'],
                       cLin['ES'], cLin['LI'], cLin['LT'],
                       np.array(cStray['ES'])/100, np.array(cStray['LI'])/100, np.array(cStray['LT'])/100,
                       np.array(Ct['ES']), np.array(Ct['LI']), np.array(Ct['LT']),
                       np.array(cPol['LI']), np.array(cPol['LT']), np.array(cPol['ES'])]

        # generate uncertainties using Monte Carlo Propagation (M=100, def line 27)
        ES_unc, LI_unc, LT_unc, ES_rel, LI_rel, LT_rel = PropagateL1B.propagate_Instrument_Uncertainty(mean_values,
                                                                                                       uncertainty)

        # return uncertainties as dictionary to be appended to xSlice
        data_wvl = np.asarray(list(stats['ES']['std_Signal'].keys()))  # get wvls
        return dict(
            esUnc=dict(zip(data_wvl, [[i] for i in ES_rel])),
            # Li_rel will be changed to unc but still be relative uncertainty
            liUnc=dict(zip(data_wvl, [[j] for j in LI_rel])),
            ltUnc=dict(zip(data_wvl, [[k] for k in LT_rel]))
        )

    def FRM(self, node, grps):
        pass

    ## Utilties
    @staticmethod
    def interp_common_wvls(columns, waves, newWavebands):
        saveTimetag2 = None
        if "Datetag" in columns:
            saveDatetag = columns.pop("Datetag")
            saveTimetag2 = columns.pop("Timetag2")
            columns.pop("Datetime")

        # Get wavelength values

        x = np.asarray(waves)

        newColumns = collections.OrderedDict()
        if saveTimetag2 is not None:
            newColumns["Datetag"] = saveDatetag
            newColumns["Timetag2"] = saveTimetag2
        # Can leave Datetime off at this point

        for i in range(newWavebands.shape[0]):
            newColumns[str(round(10*newWavebands[i])/10)] = []  # limit to one decimal place

        new_y = sp.interpolate.InterpolatedUnivariateSpline(x, columns, k=3)(newWavebands)

        for waveIndex in range(newWavebands.shape[0]):
            newColumns[str(round(10*newWavebands[waveIndex])/10)].append(new_y[waveIndex])

        return new_y, newColumns

    @staticmethod
    def interpolateSamples(Columns, waves, newWavebands):
        ''' Wavelength Interpolation for differently sized arrays containing samples
                    Use a common waveband set determined by the maximum lowest wavelength
                    of all sensors, the minimum highest wavelength, and the interval
                    set in the Configuration Window.
                    '''

        # Copy dataset to dictionary
        columns = {k: Columns[:, i] for i, k in enumerate(waves)}
        cols = []
        for m in range(Columns.shape[0]):  # across all the monte carlo draws
            newColumns = {}

            for i in range(newWavebands.shape[0]):
                # limit to one decimal place
                newColumns[str(round(10*newWavebands[i])/10)] = []

            # for m in range(Columns.shape[0]):
            # Perform interpolation for each timestamp
            y = np.asarray([columns[k][m] for k in columns])

            for waveIndex in range(newWavebands.shape[0]):
                newColumns[str(round(10*newWavebands[waveIndex])/10)].append(y[waveIndex])

            cols.append(newColumns)

        return np.asarray(cols)

    @staticmethod
    def Slaper_SL_correction(input_data, SL_matrix, n_iter=5):
        nband = len(input_data)
        m_norm = np.zeros(nband)

        mC = np.zeros((n_iter + 1, nband))
        mX = np.zeros((n_iter + 1, nband))
        mZ = SL_matrix
        mX[0, :] = input_data

        for i in range(nband):
            jstart = np.max([0, i - 10])
            jstop = np.min([nband, i + 10])
            m_norm[i] = np.sum(mZ[i, jstart:jstop])  # eq 4

        for i in range(nband):
            if m_norm[i] == 0:
                mZ[i, :] = np.zeros(nband)
            else:
                mZ[i, :] = mZ[i, :]/m_norm[i]  # eq 5

        for k in range(1, n_iter + 1):
            for i in range(nband):
                mC[k - 1, i] = mC[k - 1, i] + np.sum(mX[k - 1, :]*mZ[i, :])  # eq 6
                if mC[k - 1, i] == 0:
                    mX[k, i] = 0
                else:
                    mX[k, i] = (mX[k - 1, i]*mX[0, i])/mC[k - 1, i]  # eq 7

        return mX[n_iter - 1, :]


class HyperOCR(Instrument):
    def __init__(self):
        super().__init__()

    @staticmethod
    def _check_data(dark, light):
        msg = None
        if (dark is None) or (light is None):
            msg = f'Dark Correction, dataset not found: {dark} , {light}'
            print(msg)
            Utilities.writeLogFile(msg)
            return False

        if Utilities.hasNan(light):
            frameinfo = getframeinfo(currentframe())
            msg = f'found NaN {frameinfo.lineno}'

        if Utilities.hasNan(dark):
            frameinfo = getframeinfo(currentframe())
            msg = f'found NaN {frameinfo.lineno}'
        if msg:
            print(msg)
            Utilities.writeLogFile(msg)
        return True

    @staticmethod
    def _interp(lightData, lightTimer, darkData, darkTimer):
        # Interpolate Dark Dataset to match number of elements as Light Dataset
        newDarkData = np.copy(lightData.data)
        for k in darkData.data.dtype.fields.keys(): # For each wavelength
            x = np.copy(darkTimer.data).tolist() # darktimer
            y = np.copy(darkData.data[k]).tolist()  # data at that band over time
            new_x = lightTimer.data  # lighttimer

            if len(x) < 3 or len(y) < 3 or len(new_x) < 3:
                msg = "**************Cannot do cubic spline interpolation, length of datasets < 3"
                print(msg)
                Utilities.writeLogFile(msg)
                return False

            if not Utilities.isIncreasing(x):
                msg = "**************darkTimer does not contain strictly increasing values"
                print(msg)
                Utilities.writeLogFile(msg)
                return False
            if not Utilities.isIncreasing(new_x):
                msg = "**************lightTimer does not contain strictly increasing values"
                print(msg)
                Utilities.writeLogFile(msg)
                return False

            if len(x) >= 3:
                # Because x is now a list of datetime tuples, they'll need to be
                # converted to Unix timestamp values
                xTS = [calendar.timegm(xDT.utctimetuple()) + xDT.microsecond / 1E6 for xDT in x]
                newXTS = [calendar.timegm(xDT.utctimetuple()) + xDT.microsecond / 1E6 for xDT in new_x]

                newDarkData[k] = Utilities.interp(xTS,y,newXTS, fill_value=np.nan)

                for val in newDarkData[k]:
                    if np.isnan(val):
                        frameinfo = getframeinfo(currentframe())
                        msg = f'found NaN {frameinfo.lineno}'
            else:
                msg = '**************Record too small for splining. Exiting.'
                print(msg)
                Utilities.writeLogFile(msg)
                return False

        if Utilities.hasNan(darkData):
            frameinfo = getframeinfo(currentframe())
            msg = f'found NaN {frameinfo.lineno}'
            print(msg)
            Utilities.writeLogFile(msg)
            exit()

        return darkData.data

    @staticmethod
    def lightDarkStats(node):
        for gp in node.groups:
            if gp.attributes["FrameType"] == "ShutterDark" and gp.getDataset(sensorType):
                darkGroup = gp
                darkData = gp.getDataset(sensorType)
                darkDateTime = gp.getDataset("DATETIME")

            if gp.attributes["FrameType"] == "ShutterLight" and gp.getDataset(sensorType):
                lightGroup = gp
                lightData = gp.getDataset(sensorType)
                lightDateTime = gp.getDataset("DATETIME")

        if darkGroup is None or lightGroup is None:
            msg = f'No radiometry found for {sensorType}'
            print(msg)
            Utilities.writeLogFile(msg)
            return False

        elif not self._check_data(darkData, lightData):
            return False
        if not(newDarkData := self._interp(lightData, lightDateTime, darkData, darkDateTime)):
            return False

        # Correct light data by subtracting interpolated dark data from light data
        wvl = []
        std_Light = []
        std_Dark = []
        ave_Light = []
        ave_Dark = []
        stdevSignal = {}
        for i, k in enumerate(lightData.data.dtype.fields.keys()):
            k1 = str(float(k))
            # number of replicates for light and dark readings
            N = lightData.data.shape[0]
            Nd = newDarkData.data.shape[0]
            wvl.append(k1)

            # apply normalisation to the standard deviations used in uncertainty calculations
            std_Light.append(np.std(lightData.data[k])/pow(N, 0.5))  # = (sigma / sqrt(N))**2 or sigma**2
            std_Dark.append(np.std(newDarkData[k])/pow(Nd, 0.5))  # sigma here is essentially sigma**2 so N must be rooted
            ave_Light.append(np.average(lightData.data[k]))
            ave_Dark.append(np.average(darkData.data[k]))

            for x in range(lightData.data.shape[0]):
                lightData.data[k][x] -= newDarkData[k][x]

            # Normalised signal standard deviation =
            signalAve = np.average(lightData.data[k])
            stdevSignal[k1] = pow((pow(std_Light[-1], 2) + pow(std_Dark[-1], 2))/pow(signalAve, 2), 0.5)

            # sensitivity factor : if raw_cal==0 (or NaN), no calibration is performed and data is affected to 0
            ind_zero = np.array([rc[0] == 0 for rc in raw_cal])  # changed due to raw_cal now being a np array
            ind_nan = np.array([np.isnan(rc[0]) for rc in raw_cal])
            ind_nocal = ind_nan | ind_zero

        return dict(
            ave_Light=np.array(ave_Light),
            ave_Dark=np.array(ave_Dark),
            std_Light=np.array(std_Light),
            std_Dark=np.array(std_Dark),
            std_Signal=stdevSignal,
            wvl=wvl[ind_nocal==False]
            )

    def FRM(self, node, grps):
        # calibration of HyperOCR following the FRM processing of FRM4SOC2
        unc_grp = node.getGroup('RAW_UNCERTAINTIES')
        output = {}
        Start = {}
        End = {}
        for sensortype in ['ES', 'LI', 'LT']:
            print('FRM Processing:', sensortype)
            # Read data
            grp = node.getGroup(sensortype)

            # read in data for FRM processing
            raw_data = np.asarray(grp.getDataset(sensortype).data.tolist())
            int_time = np.asarray(grp.getDataset("INTTIME").data.tolist())

            # Read FRM characterisation
            radcal_wvl = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[1][1:].tolist())
            radcal_cal = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[2]
            dark = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[4][
                1:].tolist())  # dark signal
            S1 = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[6]
            S1_unc = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[7]/100
            S2 = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[8]
            S2_unc = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[9]/100
            mZ = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_STRAYDATA_LSF").data))
            mZ_unc = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_STRAYDATA_UNCERTAINTY").data))

            # remove 1st line and column, we work on 255 pixel not 256.
            mZ = mZ[1:, 1:]
            mZ_unc = mZ_unc[1:, 1:]

            Ct = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_TEMPDATA_CAL").data).transpose()[4][1:].tolist())
            Ct_unc = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_TEMPDATA_CAL").data).transpose()[5][1:].tolist())
            LAMP = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_LAMP").data).transpose()[2])
            LAMP_unc = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_LAMP").data).transpose()[3])/100*LAMP

            # Defined constants
            nband = len(radcal_wvl)
            nmes = len(raw_data)
            n_iter = 5

            # set up uncertainty propagation
            mDraws = 100  # number of monte carlo draws
            prop = punpy.MCPropagation(mDraws, parallel_cores=1)

            # uncertainties from data:
            sample_mZ = cm.generate_sample(mDraws, mZ, mZ_unc, "rand")
            sample_n_iter = cm.generate_sample(mDraws, n_iter, None, None, dtype=int)
            sample_Ct = cm.generate_sample(mDraws, Ct, Ct_unc, "syst")

            LAMP = np.pad(LAMP, (0, nband - len(LAMP)), mode='constant')  # PAD with zero if not 255 long
            LAMP_unc = np.pad(LAMP_unc, (0, nband - len(LAMP_unc)), mode='constant')
            sample_LAMP = cm.generate_sample(mDraws, LAMP, LAMP_unc, "syst")

            # Non-linearity alpha computation
            cal_int = radcal_cal.pop(0)
            sample_cal_int = cm.generate_sample(100, cal_int, None, None)
            t1 = S1.pop(0)
            t2 = S2.pop(0)

            sample_t1 = cm.generate_sample(mDraws, t1, None, None)
            sample_S1 = cm.generate_sample(mDraws, np.asarray(S1), S1_unc[1:], "rand")
            sample_S2 = cm.generate_sample(mDraws, np.asarray(S2), S2_unc[1:], "rand")

            k = t1/(t2 - t1)
            sample_k = cm.generate_sample(mDraws, k, None, None)
            S12 = S12func(k, S1, S2)
            sample_S12 = prop.run_samples(S12func, [sample_k, sample_S1, sample_S2])

            S12_sl_corr = Slaper_SL_correction(S12, mZ, n_iter=5)
            S12_sl_corr_unc = []
            sl4 = Slaper_SL_correction(S12, mZ, n_iter=4)
            for i in range(len(S12_sl_corr)):  # get the difference between n=4 and n=5
                if S12_sl_corr[i] > sl4[i]:
                    S12_sl_corr_unc.append(S12_sl_corr[i] - sl4[i])
                else:
                    S12_sl_corr_unc.append(sl4[i] - S12_sl_corr[i])

            sample_S12_sl_syst = cm.generate_sample(mDraws, S12_sl_corr, np.array(S12_sl_corr_unc), "syst")
            sample_S12_sl_rand = prop.run_samples(Slaper_SL_correction, [sample_S12, sample_mZ, sample_n_iter])
            sample_S12_sl_corr = prop.combine_samples([sample_S12_sl_syst, sample_S12_sl_rand])

            # alpha = ((S1-S12)/(S12**2)).tolist()
            alpha = alphafunc(S1, S12)
            sample_alpha = prop.run_samples(alphafunc, [sample_S1, sample_S12])

            # Updated calibration gain
            if sensortype == "ES":
                ## Compute avg cosine error
                avg_coserror, avg_azi_coserror, full_hemi_coserr, zenith_ang, zen_delta, azi_delta, zen_unc, azi_unc = \
                    ProcessL1b.cosine_error_correction(node, sensortype)

                # error due to lack of symmetry in cosine response
                sample_azi_delta_err1 = cm.generate_sample(mDraws, avg_azi_coserror, azi_unc, "syst")
                sample_azi_delta_err2 = cm.generate_sample(mDraws, avg_azi_coserror, azi_delta, "syst")
                sample_azi_delta_err = prop.combine_samples([sample_azi_delta_err1, sample_azi_delta_err2])
                sample_azi_err = prop.run_samples(AZAvg_Coserr, [sample_coserr, sample_coserr90])
                sample_azi_avg_coserror = prop.combine_samples([sample_azi_err, sample_azi_delta_err])

                sample_zen_delta_err1 = cm.generate_sample(mDraws, avg_coserror, zen_unc, "syst")
                sample_zen_delta_err2 = cm.generate_sample(mDraws, avg_coserror, zen_delta, "syst")
                sample_zen_delta_err = prop.combine_samples([sample_zen_delta_err1, sample_zen_delta_err2])
                sample_zen_err = prop.run_samples(ZENAvg_Coserr, [sample_radcal_wvl, sample_azi_avg_coserror])
                sample_zen_avg_coserror = prop.combine_samples([sample_zen_err, sample_zen_delta_err])

                sample_fhemi_coserr = prop.run_samples(FHemi_Coserr, [sample_zen_avg_coserror, sample_zen_ang])

                ## Irradiance direct and diffuse ratio
                res_py6s = ProcessL1b.get_direct_irradiance_ratio(node, sensortype, trios=0)

                updated_radcal_gain = Hyper_update_cal_data_ES(S12_sl_corr, LAMP, cal_int, t1)
                sample_updated_radcal_gain = prop.run_samples(Hyper_update_cal_data_ES,
                                                              [sample_S12_sl_corr, sample_LAMP, sample_cal_int,
                                                               sample_t1])
            else:
                PANEL = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_PANEL").data).transpose()[2])
                PANEL_unc = (np.asarray(
                    pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_PANEL").data).transpose()[3])/100)*PANEL
                PANEL = np.pad(PANEL, (0, nband - len(PANEL)), mode='constant')
                PANEL_unc = np.pad(PANEL_unc, (0, nband - len(PANEL_unc)), mode='constant')
                sample_PANEL = cm.generate_sample(100, PANEL, PANEL_unc, "syst")
                updated_radcal_gain = Hyper_update_cal_data_rad(S12_sl_corr, LAMP, PANEL, cal_int, t1)
                sample_updated_radcal_gain = prop.run_samples(Hyper_update_cal_data_rad,
                                                              [sample_S12_sl_corr, sample_LAMP, sample_PANEL,
                                                               sample_cal_int,
                                                               sample_t1])

            ## sensitivity factor : if gain==0 (or NaN), no calibration is performed and data is affected to 0
            ind_zero = radcal_cal <= 0
            ind_nan = np.isnan(radcal_cal)
            ind_nocal = ind_nan | ind_zero
            # set 1 instead of 0 to perform calibration (otherwise division per 0)
            updated_radcal_gain[ind_nocal == True] = 1

            # keep only defined wavelength
            updated_radcal_gain = updated_radcal_gain[ind_nocal == False]
            wvl = radcal_wvl[ind_nocal == False]
            dark = dark[ind_nocal == False]
            alpha = np.asarray(alpha)[ind_nocal == False]
            mZ = mZ[:, ind_nocal == False]
            mZ = mZ[ind_nocal == False, :]
            Ct = np.asarray(Ct)[ind_nocal == False]

            FRM_mesure = np.zeros((nmes, len(updated_radcal_gain)))

            ind_raw_data = (radcal_cal[radcal_wvl > 0]) > 0
            for n in range(nmes):
                # dark substraction
                data = raw_data[n][ind_raw_data] - dark

                # signal uncertainties
                std_light = np.std(raw_data[n][ind_raw_data], axis=0)
                std_dark = np.std(dark, axis=0)
                sample_light = cm.generate_sample(100, raw_data[n][ind_raw_data], std_light, "rand")
                sample_dark = cm.generate_sample(100, dark, std_dark, "rand")
                sample_dark_corr_data = prop.run_samples(dark_Substitution, [sample_light, sample_dark])

                # Non-linearity
                data1 = data*(1 - alpha*data)
                sample_data1 = prop.run_samples(DATA1, [sample_dark_corr_data, sample_alpha])

                # Straylight
                data2 = ProcessL1b.Slaper_SL_correction(data1, mZ, n_iter)

                S12_sl_corr_unc = []
                sl4 = Slaper_SL_correction(linear_corr_mesure, mZ, n_iter=4)
                for i in range(len(straylight_corr_mesure)):  # get the difference between n=4 and n=5
                    if linear_corr_mesure[i] > sl4[i]:
                        S12_sl_corr_unc.append(straylight_corr_mesure[i] - sl4[i])
                    else:
                        S12_sl_corr_unc.append(sl4[i] - straylight_corr_mesure[i])

                sample_straylight_1 = cm.generate_sample(mDraws, sample_data1, np.array(S12_sl_corr_unc), "syst")
                sample_straylight_2 = prop.run_samples(Slaper_SL_correction,
                                                       [sample_linear_corr_mesure, sample_mZ, sample_n_iter])
                sample_data2 = prop.combine_samples([sample_straylight_1, sample_straylight_2])

                # Calibration
                data3 = data2*(cal_int/int_time[n])/updated_radcal_gain
                sample_data3 = prop.combine_samples(DATA3, [sample_data2, sample_cal_int, sample_int_time,
                                                            sample_updated_radcal_gain])

                # thermal
                data4 = DATA4(data3, Ct)
                sample_data4 = prop.combine_samples(DATA4, [sample_data3, sample_Ct])

                # Cosine correction
                if sensortype == "ES":
                    data5 = DATA5(data4, res_py6s['solar_zenith'], res_py6s['direct_ratio'][ind_raw_data], zenith_ang,
                                  avg_coserror, full_hemi_coserror)
                    sample_data5 = prop.run_samples(DATA5, [data4, solar_zenith, direct_ratio, zenith_ang, avg_coserror,
                                                            full_hemi_coserror])
                    unc = prop.process_samples(None, sample_data5)
                    sample = sample_data5
                    FRM_mesure[n, :] = data5
                else:
                    unc = prop.process_samples(None, sample_data4)
                    sample = sample_data4
                    FRM_mesure[n, :] = data4

                # mask for arrays
                ind_zero = np.array([rc[0] == 0 for rc in raw_cal])  # changed due to raw_cal now being a np array
                ind_nan = np.array([np.isnan(rc[0]) for rc in raw_cal])
                ind_nocal = ind_nan | ind_zero

                # Remove wvl without calibration from the dataset and make uncertainties relative
                filtered_mesure = FRM_mesure[ind_nocal == False]
                filtered_unc = np.power(np.power(unc[ind_nocal == False]*1e10, 2)/np.power(filtered_mesure*1e10, 2),
                                        0.5)

                output[f"{sensortype.lower()}Wvls"] = radcal_wvl[ind_nocal == False]
                output[f"{sensortype.lower()}Unc"] = filtered_unc  # relative uncertainty
                output[f"{sensortype.lower()}Sample"] = sample[:, ind_nocal == False]  # samples keep raw

                # generate common wavebands for interpolation
                wvls = radcal_wvl[ind_nocal == False]
                Start[sensortype] = np.ceil(wvls[0])
                End[sensortype] = np.floor(wvls[-1])

            types = ['ES', 'LI', 'LT']
            # interpolate to common wavebands
            start = max([Start[stype] for stype in types])
            end = min([End[stype] for stype in types])
            newWavebands = np.arange(start, end, float(ConfigFile.settings["fL1bInterpInterval"]))

            for sensortype in types:
                # get sensor specific wavebands
                wvls = output[f"{sensortype.lower()}Wvls"]
                _, output[f"{sensortype.lower()}Unc"] = Instrument_Unc.interp_common_wvls(
                    output[f"{sensortype.lower()}Unc"],
                    wvls, newWavebands)
                output[f"{sensortype.lower()}Sample"] = Instrument_Unc.interpolateSamples(
                    output[f"{sensortype.lower()}Sample"],
                    wvls, newWavebands)

        return output


class Trios(Instrument):
    def __init__(self):
        super().__init__()

    @staticmethod
    def lightDarkStats(grp, sensortype):
        raw_cal = grp.getDataset(f"CAL_{sensortype}").data
        raw_back = grp.getDataset(f"BACK_{sensortype}").data
        raw_data = np.asarray(grp.getDataset(sensortype).data.tolist())

        raw_wvl = np.array(pd.DataFrame(grp.getDataset(sensortype).data).columns)
        int_time = np.asarray(grp.getDataset("INTTIME").data.tolist())
        DarkPixelStart = int(grp.attributes["DarkPixelStart"])
        DarkPixelStop = int(grp.attributes["DarkPixelStop"])
        int_time_t0 = int(grp.getDataset(f"BACK_{sensortype}").attributes["IntegrationTime"])

        # sensitivity factor : if raw_cal==0 (or NaN), no calibration is performed and data is affected to 0
        ind_zero = np.array([rc[0] == 0 for rc in raw_cal])  # changed due to raw_cal now being a np array
        ind_nan = np.array([np.isnan(rc[0]) for rc in raw_cal])
        ind_nocal = ind_nan | ind_zero
        raw_cal = np.array([rc[0] for rc in raw_cal])
        raw_cal[ind_nocal == True] = 1

        # slice raw_back to remove indexes where raw_cal is 0 or "NaN"
        if ConfigFile.settings['bL1bDefaultCal'] > 2:  # for some reason FRM branch keeps everything in a tuple
            raw_back = np.array([[rb[0][0] for rb in raw_back], [rb[1][0] for rb in raw_back]]).transpose()
        else:
            raw_back = np.array([[rb[0] for rb in raw_back], [rb[1] for rb in raw_back]]).transpose()

        # check size of data
        nband = len(raw_back)  # indexes changed for raw_back as is brought to L2
        nmes = len(raw_data)
        if nband != len(raw_data[0]):
            print("ERROR: different number of pixels between dat and back")
            exit()

        # Data conversion
        mesure = raw_data/65365.0
        calibrated_mesure = np.zeros((nmes, nband))
        back_mesure = np.zeros((nmes, nband))

        for n in range(nmes):
            # Background correction : B0 and B1 read from "back data"
            back_mesure[n, :] = raw_back[:, 0] + raw_back[:, 1]*(int_time[n]/int_time_t0)
            back_corrected_mesure = mesure[n] - back_mesure[n, :]

            # Offset substraction : dark index read from attribute
            offset = np.mean(back_corrected_mesure[DarkPixelStart:DarkPixelStop])
            offset_corrected_mesure = back_corrected_mesure - offset

            # Normalization for integration time
            normalized_mesure = offset_corrected_mesure*int_time_t0/int_time[n]

            # Sensitivity calibration
            calibrated_mesure[n, :] = normalized_mesure/raw_cal

        # get light and dark data before correction
        light_avg = np.mean(mesure, axis=0)[ind_nocal == False]
        light_std = np.std(mesure, axis=0)[ind_nocal == False]
        dark_avg = offset
        dark_std = np.std(back_corrected_mesure[DarkPixelStart:DarkPixelStop], axis=0)

        filtered_mesure = calibrated_mesure[:, ind_nocal == False]

        # back_avg = np.mean(back_mesure, axis=0)
        # back_std = np.std(back_mesure, axis=0)

        stdevSignal = {}
        for i, wvl in enumerate(raw_wvl[ind_nocal == False]):
            stdevSignal[wvl] = pow(
                (pow(light_std[i], 2) + pow(dark_std, 2))/pow(np.average(filtered_mesure, axis=0)[i], 2), 0.5)

        return dict(
            ave_Light=np.array(light_avg),
            ave_Dark=np.array(dark_avg),
            std_Light=np.array(light_std),
            std_Dark=np.array(dark_std),
            std_Signal=stdevSignal,
            wvl=raw_wvl[ind_nocal == False]
        )

    def FRM(self, node, grps):
        output = {}
        Start = {}
        End = {}
        for sensortype in ['ES', 'LI', 'LT']:

            ### Read HDF file inputs
            grp = grps[sensortype]

            # read data for L1B FRM processing
            raw_data = np.asarray(grp.getDataset(sensortype).data.tolist())
            DarkPixelStart = int(grp.attributes["DarkPixelStart"])
            DarkPixelStop = int(grp.attributes["DarkPixelStop"])
            int_time = np.asarray(grp.getDataset("INTTIME").data.tolist())
            int_time_t0 = int(grp.getDataset("BACK_" + sensortype).attributes["IntegrationTime"])

            ### Read full characterisation files
            unc_grp = node.getGroup('UNCERTAINTY_BUDGET')
            radcal_wvl = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[1][1:].tolist())

            ### for masking arrays only
            raw_cal = grp.getDataset(f"CAL_{sensortype}").data

            B0 = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[4][1:].tolist())
            B1 = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[5][1:].tolist())
            S1 = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[6]
            S2 = pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[8]
            mZ = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_STRAYDATA_LSF").data))
            mZ_unc = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_STRAYDATA_UNCERTAINTY").data))
            mZ = mZ[1:, 1:]  # remove 1st line and column, we work on 255 pixel not 256.
            mZ_unc = mZ_unc[1:, 1:]  # remove 1st line and column, we work on 255 pixel not 256.
            Ct = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_TEMPDATA_CAL").data).transpose()[4][1:].tolist())
            Ct_unc = np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_TEMPDATA_CAL").data).transpose()[5][1:].tolist())
            LAMP = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_LAMP").data).transpose()[2])
            LAMP_unc = (np.asarray(
                pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_LAMP").data).transpose()[3])/100)*LAMP

            # Defined constants
            nband = len(B0)
            nmes = len(raw_data)
            grp.attributes["nmes"] = nmes
            n_iter = 5

            # set up uncertainty propagation
            mDraws = 100  # number of monte carlo draws
            prop = punpy.MCPropagation(mDraws, parallel_cores=1)

            # uncertainties from data:
            sample_mZ = cm.generate_sample(mDraws, mZ, mZ_unc, "rand")
            sample_n_iter = cm.generate_sample(mDraws, n_iter, None, None, dtype=int)
            sample_int_time_t0 = cm.generate_sample(mDraws, int_time_t0, None, None)
            sample_LAMP = cm.generate_sample(mDraws, LAMP, LAMP_unc, "syst")
            sample_Ct = cm.generate_sample(mDraws, Ct, Ct_unc, "syst")

            # Non-linearity alpha computation

            t1 = S1.iloc[0]
            S1 = S1.drop(S1.index[0])
            t2 = S2.iloc[0]
            S2 = S2.drop(S2.index[0])
            sample_t1 = cm.generate_sample(mDraws, t1, None, None)

            S1 = np.asarray(S1/65535.0, dtype=float)
            S2 = np.asarray(S2/65535.0, dtype=float)
            k = t1/(t2 - t1)
            sample_k = cm.generate_sample(mDraws, k, None, None)

            S1_unc = (pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[7]/100)[1:]*np.abs(
                S1)
            S2_unc = (pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_CAL").data).transpose()[9]/100)[1:]*np.abs(
                S2)

            sample_S1 = cm.generate_sample(mDraws, np.asarray(S1), S1_unc, "rand")
            sample_S2 = cm.generate_sample(mDraws, np.asarray(S2), S2_unc, "rand")

            S12 = S12func(k, S1, S2)
            sample_S12 = prop.run_samples(S12func, [sample_k, sample_S1, sample_S2])

            S12_sl_corr = Slaper_SL_correction(S12, mZ, n_iter=5)
            S12_sl_corr_unc = []
            sl4 = Slaper_SL_correction(S12, mZ, n_iter=4)
            for i in range(len(S12_sl_corr)):  # get the difference between n=4 and n=5
                if S12_sl_corr[i] > sl4[i]:
                    S12_sl_corr_unc.append(S12_sl_corr[i] - sl4[i])
                else:
                    S12_sl_corr_unc.append(sl4[i] - S12_sl_corr[i])

            sample_S12_sl_syst = cm.generate_sample(mDraws, S12_sl_corr, np.array(S12_sl_corr_unc), "syst")
            sample_S12_sl_rand = prop.run_samples(self.Slaper_SL_correction, [sample_S12, sample_mZ, sample_n_iter])
            sample_S12_sl_corr = prop.combine_samples([sample_S12_sl_syst, sample_S12_sl_rand])

            alpha = alphafunc(S1, S12)
            alpha_unc = np.power(np.power(S1_unc, 2) + np.power(S2_unc, 2) + np.power(S2_unc, 2), 0.5)
            sample_alpha = cm.generate_sample(mDraws, alpha, alpha_unc, "syst")

            # Updated calibration gain
            if sensortype == "ES":
                # Compute avg cosine error (not done for the moment)
                cos_mean_vals, cos_uncertainties = prepare_cos(node, sensortype, 'L2')
                corr = [None, "syst", "syst", "rand"]
                sample_radcal_wvl, sample_coserr, sample_coserr90, sample_zen_ang = [
                    cm.generate_sample(mDraws, samp, cos_uncertainties[i], corr[i]) for i, samp in
                    enumerate(cos_mean_vals)]

                avg_coserror, avg_azi_coserror, full_hemi_coserr, zenith_ang, zen_delta, azi_delta, zen_unc, azi_unc = \
                    Instrument_Unc.cosine_error_correction(node, sensortype)
                # two components for cos unc, one from the file (rand), one is the difference between two symmetries

                # error due to lack of symmetry in cosine response
                sample_azi_delta_err1 = cm.generate_sample(mDraws, avg_azi_coserror, azi_unc, "syst")
                sample_azi_delta_err2 = cm.generate_sample(mDraws, avg_azi_coserror, azi_delta, "syst")
                sample_azi_delta_err = prop.combine_samples([sample_azi_delta_err1, sample_azi_delta_err2])
                sample_azi_err = prop.run_samples(mf.AZAvg_Coserr, [sample_coserr, sample_coserr90])
                sample_azi_avg_coserror = prop.combine_samples([sample_azi_err, sample_azi_delta_err])

                sample_zen_delta_err1 = cm.generate_sample(mDraws, avg_coserror, zen_unc, "syst")
                sample_zen_delta_err2 = cm.generate_sample(mDraws, avg_coserror, zen_delta, "syst")
                sample_zen_delta_err = prop.combine_samples([sample_zen_delta_err1, sample_zen_delta_err2])
                sample_zen_err = prop.run_samples(mf.ZENAvg_Coserr, [sample_radcal_wvl, sample_azi_avg_coserror])
                sample_zen_avg_coserror = prop.combine_samples([sample_zen_err, sample_zen_delta_err])

                sample_fhemi_coserr = prop.run_samples(mf.FHemi_Coserr, [sample_zen_avg_coserror, sample_zen_ang])

                # Irradiance direct and diffuse ratio
                res_py6s = ProcessL1b.get_direct_irradiance_ratio(node, sensortype, trios=0,
                                                                  L2_irr_grp=grp)  # , trios=instrument_number)
                updated_radcal_gain = mf.TriOS_update_cal_data_ES(S12_sl_corr, LAMP, int_time_t0, t1)
                sample_updated_radcal_gain = prop.run_samples(mf.TriOS_update_cal_data_ES,
                                                              [sample_S12_sl_corr, sample_LAMP, sample_int_time_t0,
                                                               sample_t1])
            else:
                PANEL = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_PANEL").data).transpose()[2])
                unc_PANEL = (np.asarray(
                    pd.DataFrame(unc_grp.getDataset(sensortype + "_RADCAL_PANEL").data).transpose()[3])/100)*PANEL
                sample_PANEL = cm.generate_sample(mDraws, PANEL, unc_PANEL, "syst")
                updated_radcal_gain = mf.TriOS_update_cal_data_rad(PANEL, S12_sl_corr, LAMP, int_time_t0, t1)
                sample_updated_radcal_gain = prop.run_samples(mf.TriOS_update_cal_data_rad,
                                                              [sample_PANEL, sample_S12_sl_corr, sample_LAMP,
                                                               sample_int_time_t0, sample_t1])

            # Data conversion
            mesure = raw_data/65365.0

            back_mesure = np.array([B0 + B1*(int_time[n]/int_time_t0) for n in range(nmes)])
            back_corrected_mesure = mesure - back_mesure
            std_light = np.std(back_corrected_mesure, axis=0)/nmes
            sample_back_corrected_mesure = cm.generate_sample(mDraws, np.mean(back_corrected_mesure, axis=0), std_light,
                                                              "rand")

            # Offset substraction : dark index read from attribute
            offset = np.mean(back_corrected_mesure[:, DarkPixelStart:DarkPixelStop], axis=1)
            offset_corrected_mesure = np.asarray(
                [back_corrected_mesure[:, i] - offset for i in range(nband)]).transpose()
            offset_std = np.std(back_corrected_mesure[:, DarkPixelStart:DarkPixelStop], axis=1)  # std in dark pixels
            std_dark = np.power((np.power(np.std(offset), 2) + np.power(offset_std, 2))/np.power(nmes, 2), 0.5)

            # add in quadrature with std in offset across scans
            sample_offset = cm.generate_sample(mDraws, np.mean(offset), np.mean(std_dark), "rand")
            sample_offset_corrected_mesure = prop.run_samples(dark_Substitution,
                                                              [sample_back_corrected_mesure, sample_offset])

            # average the signal and int_time for the station
            offset_corr_mesure = np.mean(offset_corrected_mesure, axis=0)
            int_time = np.average(int_time)

            prop = punpy.MCPropagation(mDraws, parallel_cores=1)

            # set standard variables
            n_iter = 5
            sample_n_iter = cm.generate_sample(mDraws, n_iter, None, None, dtype=int)

            # Non-Linearity Correction
            linear_corr_mesure = non_linearity_corr(offset_corr_mesure, alpha)
            sample_linear_corr_mesure = prop.run_samples(non_linearity_corr,
                                                         [sample_offset_corrected_mesure, sample_alpha])

            # Straylight Correction
            straylight_corr_mesure = Slaper_SL_correction(linear_corr_mesure, mZ, n_iter)

            S12_sl_corr_unc = []
            sl4 = Slaper_SL_correction(linear_corr_mesure, mZ, n_iter=4)
            for i in range(len(straylight_corr_mesure)):  # get the difference between n=4 and n=5
                if linear_corr_mesure[i] > sl4[i]:
                    S12_sl_corr_unc.append(straylight_corr_mesure[i] - sl4[i])
                else:
                    S12_sl_corr_unc.append(sl4[i] - straylight_corr_mesure[i])

            sample_straylight_1 = cm.generate_sample(mDraws, straylight_corr_mesure, np.array(S12_sl_corr_unc), "syst")
            sample_straylight_2 = prop.run_samples(Slaper_SL_correction,
                                                   [sample_linear_corr_mesure, sample_mZ, sample_n_iter])
            sample_straylight_corr_mesure = prop.combine_samples([sample_straylight_1, sample_straylight_2])

            # Normalization Correction, based on integration time
            normalized_mesure = straylight_corr_mesure*int_time_t0/int_time
            sample_normalized_mesure = sample_straylight_corr_mesure*int_time_t0/int_time

            # Calculate New Calibration Coeffs
            calibrated_mesure = absolute_calibration(normalized_mesure, updated_radcal_gain)
            sample_calibrated_mesure = prop.run_samples(absolute_calibration,
                                                        [sample_normalized_mesure, sample_updated_radcal_gain])

            # Thermal correction
            thermal_corr_mesure = thermal_corr(Ct, calibrated_mesure)
            sample_thermal_corr_mesure = prop.run_samples(thermal_corr, [sample_Ct, sample_calibrated_mesure])

            if sensortype.lower() == "es":
                # get cosine correction attributes and samples from dictionary
                solar_zenith = res_py6s['solar_zenith']
                direct_ratio = res_py6s['direct_ratio']
                # solar_zenith = np.array([46.87415726])
                # direct_ratio = np.array([0.222, 0.245, 0.256, 0.268, 0.279, 0.302, 0.313, 0.335, 0.345, 0.356,
                #                          0.376, 0.386, 0.396, 0.415, 0.424, 0.433, 0.45, 0.459, 0.467, 0.482,
                #                          0.489, 0.496, 0.51, 0.516, 0.522, 0.534, 0.539, 0.545, 0.555, 0.56,
                #                          0.565, 0.576, 0.581, 0.586, 0.596, 0.6, 0.605, 0.613, 0.617, 0.621,
                #                          0.629, 0.632, 0.636, 0.644, 0.647, 0.651, 0.657, 0.66, 0.663, 0.669,
                #                          0.672, 0.675, 0.68, 0.683, 0.686, 0.691, 0.693, 0.696, 0.7, 0.702,
                #                          0.705, 0.709, 0.711, 0.714, 0.717, 0.719, 0.721, 0.725, 0.726, 0.728,
                #                          0.731, 0.733, 0.736, 0.738, 0.739, 0.742, 0.744, 0.745, 0.748, 0.749,
                #                          0.75, 0.753, 0.754, 0.755, 0.757, 0.758, 0.759, 0.761, 0.763, 0.764,
                #                          0.766, 0.767, 0.768, 0.769, 0.77, 0.771, 0.773, 0.774, 0.775, 0.776,
                #                          0.777, 0.778, 0.779, 0.78, 0.781, 0.782, 0.783, 0.784, 0.785, 0.7855,
                #                          0.786, 0.788, 0.788, 0.789, 0.79, 0.79, 0.791, 0.792, 0.793, 0.793,
                #                          0.795, 0.795, 0.796, 0.797, 0.797, 0.798, 0.799, 0.799, 0.8, 0.801,
                #                          0.801, 0.802, 0.802, 0.803, 0.803, 0.804, 0.805, 0.805, 0.806, 0.806,
                #                          0.807, 0.807, 0.808, 0.808, 0.809, 0.809, 0.81, 0.81, 0.811, 0.811,
                #                          0.811, 0.812, 0.812, 0.813, 0.813, 0.814, 0.814, 0.814, 0.815, 0.815,
                #                          0.816, 0.816, 0.816, 0.817, 0.817, 0.817, 0.818, 0.818, 0.818, 0.819,
                #                          0.819, 0.819, 0.819, 0.82, 0.82, 0.821, 0.821, 0.821, 0.822, 0.822,
                #                          0.822, 0.822, 0.823, 0.823, 0.823, 0.824, 0.824, 0.824, 0.824, 0.825,
                #                          0.825, 0.825, 0.826, 0.826, 0.826, 0.826, 0.827, 0.827, 0.827, 0.827,
                #                          0.828, 0.828, 0.828, 0.828, 0.828, 0.829, 0.829, 0.829, 0.829, 0.83,
                #                          0.83, 0.83, 0.83, 0.83, 0.83, 0.831, 0.831, 0.831, 0.831, 0.831,
                #                          0.832, 0.832, 0.832, 0.832, 0.832, 0.832, 0.833, 0.833, 0.833, 0.833,
                #                          0.833, 0.833, 0.834, 0.834, 0.834, 0.834, 0.834, 0.834, 0.834, 0.835,
                #                          0.835, 0.835, 0.835, 0.835, 0.835, 0.835, 0.836, 0.836, 0.836, 0.836,
                #                          0.836, 0.836, 0.836, 0.836, 0.837])

                sample_sol_zen = cm.generate_sample(mDraws, solar_zenith,
                                                    np.asarray([0.05 for i in range(len(solar_zenith))]),
                                                    "rand")  # TODO: get second opinion on zen unc in 6S
                sample_dir_rat = cm.generate_sample(mDraws, direct_ratio, 0.08*direct_ratio, "syst")

                ind_closest_zen = np.argmin(np.abs(zenith_ang - solar_zenith))
                cos_corr = 1 - avg_coserror[:, ind_closest_zen]/100
                Fhcorr = 1 - np.array(full_hemi_coserr)/100
                cos_corr_mesure = (direct_ratio*thermal_corr_mesure*cos_corr) + (
                        (1 - direct_ratio)*thermal_corr_mesure*Fhcorr)

                FRM_mesure = cos_corr_mesure
                sample_cos_corr_mesure = prop.run_samples(cosine_corr,
                                                          [sample_zen_avg_coserror, sample_fhemi_coserr, sample_zen_ang,
                                                           sample_thermal_corr_mesure, sample_sol_zen, sample_dir_rat])
                cos_unc = prop.process_samples(None, sample_cos_corr_mesure)

                unc = cos_unc
                sample = sample_cos_corr_mesure
            else:
                FRM_mesure = thermal_corr_mesure
                sample = sample_thermal_corr_mesure
                unc = prop.process_samples(None, sample_thermal_corr_mesure)

            # mask for arrays
            ind_zero = np.array([rc[0] == 0 for rc in raw_cal])  # changed due to raw_cal now being a np array
            ind_nan = np.array([np.isnan(rc[0]) for rc in raw_cal])
            ind_nocal = ind_nan | ind_zero

            # Remove wvl without calibration from the dataset and make uncertainties relative
            filtered_mesure = FRM_mesure[ind_nocal == False]
            filtered_unc = np.power(np.power(unc[ind_nocal == False]*1e10, 2)/np.power(filtered_mesure*1e10, 2), 0.5)

            output[f"{sensortype.lower()}Wvls"] = radcal_wvl[ind_nocal == False]
            output[
                f"{sensortype.lower()}Unc"] = filtered_unc  # dict(zip(str_wvl[ind_nocal==False], filtered_unc))  # unc in dict with wavelengths
            output[f"{sensortype.lower()}Sample"] = sample[:, ind_nocal == False]  # samples keep raw

            # generate common wavebands for interpolation
            wvls = radcal_wvl[ind_nocal == False]
            Start[sensortype] = np.ceil(wvls[0])
            End[sensortype] = np.floor(wvls[-1])

        types = ['ES', 'LI', 'LT']
        # interpolate to common wavebands
        start = max([Start[stype] for stype in types])
        end = min([End[stype] for stype in types])
        newWavebands = np.arange(start, end, float(ConfigFile.settings["fL1bInterpInterval"]))

        for sensortype in types:
            # get sensor specific wavebands
            wvls = output[f"{sensortype.lower()}Wvls"]
            _, output[f"{sensortype.lower()}Unc"] = Instrument_Unc.interp_common_wvls(
                output[f"{sensortype.lower()}Unc"], wvls, newWavebands)
            output[f"{sensortype.lower()}Sample"] = Instrument_Unc.interpolateSamples(
                output[f"{sensortype.lower()}Sample"], wvls, newWavebands)

        return output  # return products as dictionary to be appended to xSlice
