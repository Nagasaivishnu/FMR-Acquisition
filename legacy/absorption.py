
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from scipy.signal import detrend
from scipy.signal import savgol_filter


def absorption_spectrum():
    file_paths = {}
    
    #file_paths["Antidot"] = r"C:\Users\Simulation\Documents\Test\FMR\antidot_PY\antidot_PY_LOR_500uV_FMR_mmWave7.0GHz_power0dBm_lockin_amp4V_freq_113.52.csv"
    # file_paths["Wire"] = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_long_run\CO_wire_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52.csv"
    # file_paths["Wire_on_antidot"] = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_on_PY_antidot_long_run\CO_wire_on_PY_antidot_500uV_FMR_mmWave7.0GHz_power-3dBm_lockin_amp4V_freq_113.52.csv"
    # file_paths["Wire_90deg"] = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_90deg_long_run\CO_wire_90deg_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # file_paths["Wire_on_antidot_90deg"] = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_on_PY_antidot_90deg_long_run\CO_wire_on_PY_antidot_500uV_FMR_mmWave7.0GHz_power-3dBm_lockin_amp4V_freq_113.52.csv"
    # file_paths["Wire_on_antidot_sample2"] = r"C:\Users\Simulation\Documents\Test\FMR\CO_wire_on_PY_antidot_sample2_test\CO_wire_on_PY_antidot_sample2_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # file_paths["PY_antidot_sample2"] = r"C:\Users\Simulation\Documents\Test\FMR\PY_antidot_sample2_test\PY_antidot_sample2_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # file_paths["silicon_sample"] = r"C:\Users\Simulation\Documents\Test\FMR\silicon_sample_test\silicon_sample_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # file_paths["background"] = r"C:\Users\Simulation\Documents\Test\FMR\background_test\background_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # file_paths["leon"] = r"C:\Users\Simulation\Documents\Test\FMR\Leon_antidot_PY_long_scan\Leon_antidot_PY_100uV_FMR_mmWave7.0GHz_power0dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    

    file_paths["Dot_with PY"] = r"C:\Users\Simulation\Documents\Test\FMR\antidot_manual\antidot_PY_LOR_500uV_FMR_mmWave7.1GHz_power0dBm_lockin_amp4V_freq_113.52.csv"
    background_files = {}
    background_files["Dot_with PY"] = r"C:\Users\Simulation\Documents\Test\FMR\background_0db\background_100uV_FMR_mmWave7.1GHz_power0dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    # background_files["Wire"] = r"C:\Users\Simulation\Documents\Test\FMR\background_test\background_100uV_FMR_mmWave7.0GHz_power-5dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    #background_files["Antidot"] = r"C:\Users\Simulation\Documents\Test\FMR\background_0db\background_100uV_FMR_mmWave7.0GHz_power0dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    #background_files["leon"] = r"C:\Users\Simulation\Documents\Test\FMR\background_0db\background_100uV_FMR_mmWave7.0GHz_power0dBm_lockin_amp4V_freq_113.52_filter_18.csv"
    
    # background_files["Wire_on_antidot"] = r"C:\Users\Simulation\Documents\Test\FMR\background_-3db\background_100uV_FMR_mmWave7.0GHz_power-3dBm_lockin_amp4V_freq_113.52_filter_18.csv"


    fig, ax1 = plt.subplots()
    for key, file_path in file_paths.items():
        data = pd.read_csv(file_path)
        background_data = pd.read_csv(background_files.get(key, ""))
        
        volx = data['voltageX']#[:500]
        voly = data['voltageY']#[:500]
        H_field = data['field']#[:500]
        current = data['Current']

        background_data_volx = background_data['voltageX']#[:500]
        background_data_voly = background_data['voltageY']#[:500]
        H_field_background = background_data['field']#[:500]

        volx = volx# - background_data_volx[:len(volx)]
        voly = voly# - background_data_voly[:len(voly)]
        max_x = max(volx)
        max_y = max(voly)
        
        
        phase = np.atan(voly/volx)

        transformed_x = []
        transformed_y = []

        for i in range(len(volx)):
            theta = np.arctan2(voly[i], volx[i])
            transformed_x.append(volx[i]*np.cos(theta) + (voly[i]*np.sin(theta)))
            transformed_y.append(-volx[i]*np.sin(theta) + (voly[i]*np.cos(theta)))
        
        integrated_data = []
        su = 0

        R = np.sqrt(np.array(volx)**2 + np.array(voly)**2)
        bg_R = np.sqrt(np.array(background_data_volx)**2 + np.array(background_data_voly)**2)

        from scipy.integrate import cumulative_trapezoid

    # Convert to numpy arrays (important)
        H = np.array(H_field)
        signal1 = np.array(R)  # Remove mean if necessary
        signal2 = np.array(R) - np.array(bg_R[:len(R)])# - (np.mean(np.array(R) - np.array(bg_R[:len(R)])))  # Remove mean if necessary
        #signal1 = np.array(transformed_x) - np.mean(np.array(transformed_x))
        #signal2 = detrend(transformed_x)  # Remove linear trend if necessary

        smooth = savgol_filter(signal1, 21, 3)  # window size 11, polynomial order 3
        integrated_data1 = cumulative_trapezoid(signal1 - np.mean(signal1), H, initial=0)
        integrated_data2 = cumulative_trapezoid(signal2 - np.mean(signal2), H, initial=0)
        bg_integrated_data = detrend(cumulative_trapezoid(detrend(bg_R[:len(H)] - np.mean(bg_R)), H, initial=0))
        #integrated_data3 = cumulative_trapezoid(signal2, H, initial=0)

        #expo = detrend(np.exp(np.exp(integrated_data2/max(integrated_data2))))

        
        #ax1.plot(H, integrated_data1, label=key)
        ax1.plot(H, phase, label=f'{key} background subtracted')
        #ax1.plot(H, signal2, label=f'{key} background subtracted')
        #ax1.plot(H, bg_integrated_data[:len(H)], label=f'{key} background', alpha=0.5)
        ax1.set_xlabel('Magnetic Field')
        ax1.set_ylabel('absorption')
        ax1.legend(loc='upper left')
        #ax1.tick_params(axis='y', labelcolor='blue')

        #Second signal (right y-axis)
        # ax2 = ax1.twinx()
        #  # window size 11, polynomial order 3
        # ax2.plot(H, background_data_volx[:len(H)], label='Integrated Detrended Signal', color='red')
        # ax2.set_ylabel('Detrended Signal', color='red')
        # ax2.tick_params(axis='y', labelcolor='red')

        # plt.title("FMR Signal Comparison")
    
    plt.legend()
    plt.show()

absorption_spectrum()