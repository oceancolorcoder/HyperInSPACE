import os
import datetime as dt
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

from Source.ConfigFile import ConfigFile
from Source.MainConfig import MainConfig
from Source.ProcessL1b import ProcessL1b
from Source.ProcessL1b_FRMCal import ProcessL1b_FRMCal
from Source.ProcessL1b_Interp import ProcessL1b_Interp
from Source.Utilities import Utilities
from Source.Uncertainty_Analysis import Propagate
from Source.GetAnc import GetAnc
from Source.GetAnc_ecmwf import GetAnc_ecmwf
# from FidradDB_api import FidradDB_api

class TriosL1B:


    @staticmethod
    def processDarkCorrection_FRM(node, sensortype, stats: dict):
        # Dark & Calibration process for FRM branch using Full Characterisation from TO,
        # and with additional correction for (non-linearity, straylight, ...)

        ### Read HDF file inputs
        # grp = node.getGroup(instrument_number+'.dat')
        grp = node.getGroup(sensortype)
        raw_data = np.asarray(grp.getDataset(sensortype).data.tolist())
        DarkPixelStart = int(grp.attributes["DarkPixelStart"])
        DarkPixelStop  = int(grp.attributes["DarkPixelStop"])
        int_time = np.asarray(grp.getDataset("INTTIME").data.tolist())
        int_time_t0 = int(grp.getDataset("BACK_"+sensortype).attributes["IntegrationTime"])

        ### Read full characterisation files
        unc_grp = node.getGroup('RAW_UNCERTAINTIES')
        radcal_wvl = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['1'][1:].tolist())
        str_wvl = np.asarray([str(x) for x in radcal_wvl])
        # radcal_cal = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['2'][1:].tolist())
        B0 = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['4'][1:].tolist())
        B1 = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['5'][1:].tolist())
        S1 = pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['6']
        S2 = pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_CAL").data)['8']
        mZ = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_STRAYDATA_LSF").data))
        mZ = mZ[1:,1:] # remove 1st line and column, we work on 255 pixel not 256.
        Ct = pd.DataFrame(unc_grp.getDataset(sensortype+"_TEMPDATA_CAL").data)[sensortype+"_TEMPERATURE_COEFFICIENTS"][1:].tolist()

        LAMP = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_LAMP").data)['2'])

        # Defined constants
        nband = len(B0)
        nmes  = len(raw_data)
        n_iter = 5

        # Non-linearity alpha computation
        t1 = S1.pop(0)
        t2 = S2.pop(0)
        S1 = S1/65535.0
        S2 = S2/65535.0
        k = t1/(t2-t1)
        S12 = (1+k)*S1 - k*S2
        S12_sl_corr = ProcessL1b_FRMCal.Slaper_SL_correction(S12, mZ, n_iter)
        alpha = ((S1-S12)/(S12**2)).tolist()

        # Updated calibration gain
        if sensortype == "ES":
            updated_radcal_gain = (S12_sl_corr/LAMP) * (int_time_t0/t1)
            # Compute avg cosine error (not done for the moment)
            avg_coserror, full_hemi_coserror, zenith_ang = ProcessL1b_FRMCal.cosine_error_correction(node, sensortype)
            # Irradiance direct and diffuse ratio
            res_py6s = ProcessL1b_FRMCal.get_direct_irradiance_ratio(node, sensortype)
        else:
            PANEL = np.asarray(pd.DataFrame(unc_grp.getDataset(sensortype+"_RADCAL_PANEL").data)['2'])
            updated_radcal_gain = (np.pi*S12_sl_corr)/(LAMP*PANEL) * (int_time_t0/t1)

        # sensitivity factor : if gain==0 (or NaN), no calibration is performed and data is affected to 0
        ind_zero = (updated_radcal_gain<=1e-2)
        ind_nan  = np.isnan(updated_radcal_gain)
        ind_nocal = ind_nan | ind_zero
        updated_radcal_gain[ind_nocal==True] = 1 # set 1 instead of 0 to perform calibration (otherwise division per 0)

        # Data conversion
        mesure = raw_data/65365.0
        FRM_mesure = np.zeros((nmes, nband))
        back_mesure = np.zeros((nmes, nband))

        for n in range(nmes):
            # Background correction : B0 and B1 read from full charaterisation
            back_mesure[n,:] = B0 + B1*(int_time[n]/int_time_t0)
            back_corrected_mesure = mesure[n] - back_mesure[n,:]
            # Offset substraction : dark index read from attribute
            offset = np.mean(back_corrected_mesure[DarkPixelStart:DarkPixelStop])
            offset_corrected_mesure = back_corrected_mesure - offset
            # Non-linearity correction
            linear_corr_mesure = offset_corrected_mesure*(1-alpha*offset_corrected_mesure)
            # Straylight correction over measurement
            straylight_corr_mesure = ProcessL1b_FRMCal.Slaper_SL_correction(linear_corr_mesure, mZ, n_iter)
            # Normalization for integration time
            normalized_mesure = straylight_corr_mesure * int_time_t0/int_time[n]
            # Absolute calibration
            # calibrated_mesure_origin = (offset_corrected_mesure*int_time_t0/int_time[n])/radcal_cal
            calibrated_mesure = normalized_mesure/updated_radcal_gain
            # Thermal correction
            thermal_corr_mesure = Ct*calibrated_mesure
            # Cosine correction : commented for the moment
            if sensortype == "ES":
                solar_zenith = res_py6s['solar_zenith']
                direct_ratio = res_py6s['direct_ratio']
                ind_closest_zen = np.argmin(np.abs(zenith_ang-solar_zenith))
                cos_corr = 1-avg_coserror[:,ind_closest_zen]/100
                Fhcorr = 1-full_hemi_coserror/100
                cos_corr_mesure = (direct_ratio*thermal_corr_mesure*cos_corr) + ((1-direct_ratio)*thermal_corr_mesure*Fhcorr)
                FRM_mesure[n,:] = cos_corr_mesure

            else:
                FRM_mesure[n,:] = thermal_corr_mesure

        # Remove wvl without calibration from the dataset
        # unit conversion from mW/m2 to uW/cm2 : divide per 10
        filtered_mesure = FRM_mesure[:,ind_nocal==False]/10
        filtered_wvl = str_wvl[ind_nocal==False]

        # Replace raw data with calibrated data in hdf root
        ds_dt = np.dtype({'names': filtered_wvl,'formats': [np.float64]*len(filtered_wvl)})
        rec_arr = np.rec.fromarrays(np.array(filtered_mesure).transpose(), dtype=ds_dt)
        grp.getDataset(sensortype).data = rec_arr

        # Rename the group from serial_numer to frame type
        grp.id = sensortype

        # Get light and dark data before correction
        light_avg = np.mean(mesure, axis=0)
        back_avg  = np.mean(back_mesure, axis=0)
        light_std = np.std(mesure, axis=0)
        back_std  = np.std(back_mesure, axis=0)
        stdevSignal = {}
        for i, wvl in enumerate(str_wvl):
            stdevSignal[wvl] = pow((pow(light_std[i],2) + pow(back_std[i], 2)) / pow(light_avg[i], 2), 0.5)

        stats[sensortype] = {'ave_Light': np.array(light_avg), 'ave_Dark': np.array(back_avg),
                          'std_Light': np.array(light_std), 'std_Dark': np.array(back_std),
                          'std_Signal': stdevSignal, 'wvl':str_wvl}  # std_Signal stored as dict to help when interpolating wavebands

        return True

    @staticmethod
    def processDarkCorrection(node, sensortype, stats: dict):
        # Dark correction performed for each trios radiometers
        # Instrument serial number and associated frame type are read in configuration
        # return the wvl of dark pixel for which no calibration factor is defined

        # Read HDF file inputs
        # grp = node.getGroup(instrument_number+'.dat')
        grp = node.getGroup(sensortype)
        grp.getDataset("CAL_"+sensortype).datasetToColumns()
        raw_cal = np.array(grp.getDataset("CAL_"+sensortype).columns['0'])
        # raw_cal  = np.array(grp.getDataset("CAL_"+sensortype).data.tolist())
        raw_back = np.asarray(grp.getDataset("BACK_"+sensortype).data.tolist())
        raw_data = np.asarray(grp.getDataset(sensortype).data.tolist())
        raw_wvl = np.array(pd.DataFrame(grp.getDataset(sensortype).data).columns)
        int_time = np.asarray(grp.getDataset("INTTIME").data.tolist())
        DarkPixelStart = int(grp.attributes["DarkPixelStart"])
        DarkPixelStop  = int(grp.attributes["DarkPixelStop"])
        int_time_t0 = int(grp.getDataset("BACK_"+sensortype).attributes["IntegrationTime"])

        # check size of data
        nband = len(raw_back[:,0])
        nmes = len(raw_data)
        if nband != len(raw_data[0]):
            print("ERROR: different number of pixel between dat and back")
            exit()

        # sensitivity factor : if raw_cal==0 (or NaN), no calibration is performed and data is affected to 0
        ind_zero = (raw_cal==0)
        ind_nan  = np.isnan(raw_cal)
        ind_nocal = ind_nan | ind_zero
        raw_cal[ind_nocal==True] = 1 # set 1 instead of 0 to perform calibration (otherwise division per 0)

        # Data conversion
        mesure = raw_data/65365.0
        calibrated_mesure = np.zeros((nmes, nband))
        back_mesure = np.zeros((nmes, nband))
        for n in range(nmes):
            # Background correction : B0 and B1 read from "back data"
            back_mesure[n,:] = raw_back[:,0] +  raw_back[:,1]*(int_time[n]/int_time_t0)
            back_corrected_mesure = mesure[n] - back_mesure[n,:]

            # Offset substraction : dark index read from attribute
            offset = np.mean(back_corrected_mesure[DarkPixelStart:DarkPixelStop])
            offset_corrected_mesure = back_corrected_mesure - offset

            # Normalization for integration time
            normalized_mesure = offset_corrected_mesure * int_time_t0/int_time[n]

            # Sensitivity calibration
            calibrated_mesure[n,:] = normalized_mesure/raw_cal

            # # When no calibration available, set data to 0.
            # calibrated_mesure[n, ind_nocal==True] = 0.  # not used at the moment

        # Remove wvl without calibration from the dataset
        # unit conversion from mW/m2 to uW/cm2 : divide per 10
        filtered_mesure = calibrated_mesure[:,ind_nocal==False]/10
        filtered_wvl = raw_wvl[ind_nocal==False]

        # replace raw data with calibrated data in hdf root
        ds_dt = np.dtype({'names': filtered_wvl,'formats': [np.float64]*len(filtered_wvl)})
        rec_arr = np.rec.fromarrays(np.array(filtered_mesure).transpose(), dtype=ds_dt)
        grp.getDataset(sensortype).data = rec_arr
        # And rename the group from serial_numer to frame type
        # grp.id = sensortype

        # get light and dark data before correction
        light_avg = np.mean(mesure, axis=0)
        back_avg = np.mean(back_mesure, axis=0)
        light_std = np.std(mesure, axis=0)
        back_std = np.std(back_mesure, axis=0)
        stdevSignal = {}
        for i, wvl in enumerate(raw_wvl):
            stdevSignal[wvl] = pow((pow(light_std[i],2) + pow(back_std[i], 2)) / pow(light_avg[i], 2), 0.5)

        stats[sensortype] = {'ave_Light': np.array(light_avg), 'ave_Dark': np.array(back_avg),
                          'std_Light': np.array(light_std), 'std_Dark': np.array(back_std),
                          'std_Signal': stdevSignal, 'wvl':raw_wvl}  # std_Signal stored as dict to help when interpolating wavebands
        return True



    @staticmethod
    def processL1b(node, outFilePath):
        '''
        TriOS pathway. Switch to common pathway at ProcessL1b_Interp.processL1b_Interp.
        Apply dark shutter correction to light data. Then apply either default factory cals
        or full instrument characterization. Introduce uncertainty group.
        Match timestamps and interpolate wavebands.
        '''
        node.attributes["PROCESSING_LEVEL"] = "1B"
        now = dt.datetime.now()
        timestr = now.strftime("%d-%b-%Y %H:%M:%S")
        node.attributes["FILE_CREATION_TIME"] = timestr
        node.attributes['WAVE_INTERP'] = str(ConfigFile.settings['fL1bInterpInterval']) + ' nm'
        if ConfigFile.settings["bL1bCal"] == 1:
            node.attributes['CAL_TYPE'] = 'Factory'
        elif ConfigFile.settings["bL1bCal"] == 2:
            node.attributes['CAL_TYPE'] = 'Class-based'
        elif ConfigFile.settings["bL1bCal"] == 3:
            node.attributes['CAL_TYPE'] = 'Instrument-based'

        msg = f"TriosL1B.processL1b: {timestr}"
        print(msg)
        Utilities.writeLogFile(msg)

        # Retain L1BQC data for L2 instrument uncertainty analysis
        for gp in node.groups:
            if gp.id == 'ES' or gp.id == 'LI' or gp.id == 'LT':
                newGroup = node.addGroup(gp.id+'_L1AQC')
                newGroup.copy(gp)
                for ds in newGroup.datasets:
                    if ds == 'DATETIME':
                        del(gp.datasets[ds])
                    elif ds.startswith('BACK_') or ds.startswith('CAL_'):
                        continue
                    else:
                        newGroup.datasets[ds].datasetToColumns()
        
        # Add a dataset to each group for DATETIME, as defined by TIMETAG2 and DATETAG
        node  = Utilities.rootAddDateTime(node)


        # Add Class-based characterization files if needed (RAW_UNCERTAINTIES)
        if ConfigFile.settings['bL1bCal'] == 1:
            print("Factory TriOS RAMSES - no uncertainty computation")


        # Add Class-based characterization files + RADCAL files
        elif ConfigFile.settings['bL1bCal'] == 2:
            classbased_dir = os.path.join('Data', 'Class_Based_Characterizations', ConfigFile.settings['SensorType']+"_initial")
            radcal_dir = ConfigFile.settings['RadCalDir']           
            print("Class-Based - uncertainty computed from class-based and RADCAL")
            print('Class-Based:', classbased_dir)
            print('RADCAL:', radcal_dir)
            node = ProcessL1b.read_unc_coefficient_class(node, classbased_dir, radcal_dir)
            if node is None:
                msg = 'Error running class based uncertainties.'
                print(msg)
                Utilities.writeLogFile(msg)
                return None

        # Or add Full characterization files (RAW_UNCERTAINTIES)
        elif ConfigFile.settings['bL1bCal'] == 3:

            if ConfigFile.settings['FidRadDB'] == 0:
                inpath = ConfigFile.settings['FullCalDir']
                print("Full-Char - uncertainty computed from full characterization")
                print('Full-Char dir:', inpath)
                
            # elif ConfigFile.settings['FidRadDB'] == 1:
            #     sensorID = Utilities.get_sensor_dict(node)
            #     acq_time = node.attributes["TIME-STAMP"].replace('_','')
            #     inpath = os.path.join('Data', 'FidRadDB_characterization', "TriOS", acq_time)
            #     print('FidRadDB Char dir:', inpath)

            #     # FidRad DB connection and download of calibration files by api
            #     types = ['STRAY','RADCAL','POLAR','THERMAL','ANGULAR']
            #     for sensor in sensorID:
            #         for sens_type in types:
            #             try:
            #                 FidradDB_api(sensor+'_'+sens_type, acq_time, inpath)
            #             except: None

            #     # Check the number of cal files
            #     cal_count = 0
            #     for root_dir, cur_dir, files in os.walk(inpath):
            #         cal_count += len(files)
            #     if cal_count !=12:
            #         print("The number of calibration files doesn't match with the required number (12).")
            #         print("Aborting")
            #         exit()

            node = ProcessL1b.read_unc_coefficient_frm(node, inpath)
            if node is None:
                msg = 'Error loading FRM characterization files. Check directory.'
                print(msg)
                Utilities.writeLogFile(msg)
                return None

        # Interpolate only the Ancillary group, and then fold in model data
        if not ProcessL1b_Interp.interp_Anc(node, outFilePath):
            msg = 'Error interpolating ancillary data'
            print(msg)
            Utilities.writeLogFile(msg)
            return None

        # Need to fill in with model data here. This had previously been run on the GPS group, but now shifted to Ancillary group
        ancGroup = node.getGroup("ANCILLARY_METADATA")
        # Retrieve MERRA2 model ancillary data
        if ConfigFile.settings["bL1bGetAnc"] ==1:
            msg = 'MERRA2 data for Wind and AOD may be used to replace blank values. Reading in model data...'
            print(msg)
            Utilities.writeLogFile(msg)
            modRoot = GetAnc.getAnc(ancGroup)
        # Retrieve ECMWF model ancillary data
        elif ConfigFile.settings["bL1bGetAnc"] == 2:
            msg = 'ECMWF data for Wind and AOD may be used to replace blank values. Reading in model data...'
            print(msg)
            Utilities.writeLogFile(msg)
            modRoot = GetAnc_ecmwf.getAnc_ecmwf(ancGroup)
        else:
            modRoot = None

        if modRoot is not None:
            # Regardless of whether SolarTracker/pySAS is used, Ancillary data will have been already been
            # interpolated in L1B as long as the ancillary file was read in at L1AQC. Regardless, these need
            # to have model data and/or default values incorporated.

            # If GMAO modeled data is selected in ConfigWindow, and an ancillary field data file
            # is provided in Main Window, then use the model data to fill in gaps in the field
            # record. Otherwise, use the selected default values from ConfigWindow

            # This step is only necessary for the ancillary datasets that REQUIRE
            # either field or GMAO or GUI default values. The remaining ancillary data
            # are culled from datasets in groups in L1B
            ProcessL1b.includeModelDefaults(ancGroup, modRoot)

        ## Dark Correction & Absolute Calibration
        stats = {}
        for instrument in ConfigFile.settings['CalibrationFiles'].keys():
            # get instrument serial number and sensor type
            instrument_number = os.path.splitext(instrument)[0]
            sensortype = ConfigFile.settings['CalibrationFiles'][instrument]['frameType']
            enabled = ConfigFile.settings['CalibrationFiles'][instrument]['enabled']
            if enabled:
                msg = f'Dark Correction: {instrument_number} - {sensortype}'
                print(msg)
                Utilities.writeLogFile(msg)

                '''
                Are Factory and Class-based approaches identical for TriOS?
                Shouldn't Factory be based on factory cal file formats?
                '''
                if ConfigFile.settings["bL1bCal"] <= 2:
                    if not TriosL1B.processDarkCorrection(node, sensortype, stats):
                        msg = f'Error in TriosL1B.processDarkCorrection: {instrument_number} - {sensortype}'
                        print(msg)
                        Utilities.writeLogFile(msg)
                        return None
                elif ConfigFile.settings['bL1bCal'] == 3:
                    if not TriosL1B.processDarkCorrection_FRM(node, sensortype, stats):
                        msg = f'Error in TriosL1B.processDarkCorrection_FRM: {instrument_number} - {sensortype}'
                        print(msg)
                        Utilities.writeLogFile(msg)
                        return None
            
                    
            
        ## Interpolation
        # Match instruments to a common timestamp (slowest shutter, should be Lt) and
        # interpolate to the chosen spectral resolution. HyperSAS instruments operate on
        # different timestamps and wavebands, so interpolation is required.
        node = ProcessL1b_Interp.processL1b_Interp(node, outFilePath)
        

        node.attributes["LI_UNITS"] = 'uW/cm^2/nm/sr'
        node.attributes["LT_UNITS"] = 'uW/cm^2/nm/sr'
        node.attributes["ES_UNITS"] = 'uW/cm^2/nm'

        return node
