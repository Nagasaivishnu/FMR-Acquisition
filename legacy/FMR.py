from pna import NetworkAnalyser
import time
import matplotlib.pyplot as plt
from pymeasure.instruments.kepco import KepcoBOP3612
from pymeasure.instruments.lakeshore import LakeShore425
from pymeasure.instruments.srs import SR830
import numpy as np
from scipy.optimize import curve_fit
from scipy.constants import mu_0
import pandas as pd
import yaml
from pathlib import Path






def py_fmr(output_folder,smaple_identity, microwave_frequency, microwave_power, curr_range_min, curr_range_max, curr_interval, lockin_amp, lockin_freq, lockin_sens, lockin_phase=0, lockin_filter_slope=12):
    gaussmter = LakeShore425('COM4')
    gaussmter.unit = "T"
    lockinamp = SR830('GPIB0::8::INSTR')
    powersupply = KepcoBOP3612('GPIB0::6::INSTR')
    networkan = NetworkAnalyser()
    

    networkan.generate_signal(microwave_frequency, microwave_power)
    powersupply.operating_mode = 'CURR'
    powersupply.output_enabled = True
    powersupply.voltage_setpoint = 14
    powersupply.current_setpoint = curr_range_min
    lockinamp.sine_voltage = lockin_amp
    lockinamp.frequency = lockin_freq
    lockinamp.phase = lockin_phase
    lockinamp.filter_slope = lockin_filter_slope
    
    #lockinamp.sensitivity = lockin_sens

    time.sleep(5)
    volx = []
    voly = []
    currs = []
    field = []
    curr = curr_range_min
    time.sleep(5)
    if curr_range_min > curr_range_max:
        while curr >= curr_range_max:
            powersupply.current_setpoint = curr
            print(round(curr, 4))
            time.sleep(0.3)
            curr = curr - curr_interval
            volx.append(lockinamp.x)
            voly.append(lockinamp.y)
            currs.append(curr)
            field.append(gaussmter.field)
    else:
        while curr <= curr_range_max:
            powersupply.current_setpoint = curr
            print(round(curr, 4))
            time.sleep(0.3)
            curr = curr + curr_interval
            volx.append(lockinamp.x)
            voly.append(lockinamp.y)
            currs.append(curr)
            field.append(gaussmter.field)
    file_name = f"{smaple_identity}_FMR_mmWave{microwave_frequency/1E9}GHz_power{microwave_power}dBm_lockin_amp{lockin_amp}V_freq_{lockin_freq}_filter_{lockin_filter_slope}.csv"
    file_path = Path(__file__).parent.joinpath(output_folder).joinpath(file_name)
    file_path.parent.mkdir(parents=True, exist_ok=True)  # Create directory if missing
    print(file_path)


    with open(file_path, 'w') as file:
        file.write(f"Current,field,voltageX,voltageY\n")
        for i in range(len(currs)):
            file.write(f"{round(currs[i],4)},{field[i]},{volx[i]},{voly[i]}\n")
        

    return file_path

def rotation_matrix_2d(theta):
    return np.array([[np.cos(theta), -np.sin(theta)],
                     [np.sin(theta), np.cos(theta)]])

def vo_func(H, A, H_res, delta_H, b, c):
    return (A * (H - H_res)) / (((H - H_res)**2 + (delta_H / 2)**2)**2) + b * H + c

def post_process(file_name: Path, frequency):

    data = pd.read_csv(file_name)
    volx = data['voltageX']
    voly = data['voltageY']
    H_field = data['field']
    current = data['Current']

    # max_x = volx[volx.index[volx == volx.max()]].values[0]
    # max_y = voly[volx.index[volx == volx.max()]].values[0]
    # #H_field = current * 263.66
    
    # theta = np.atan(voly[100]/volx[100])
    # theta = np.deg2rad(-45)  # for phase 90 degree

    idx = np.argmax(np.abs(volx))   # index of strongest signal
    theta = np.arctan2(voly[idx], volx[idx])
    print(theta)
    #theta = np.atan(max_y/max_x)

    transformed_x = []
    transformed_y = []

    transformed_x = volx*np.cos(theta) + (voly*np.sin(theta))
    transformed_y = -volx*np.sin(theta) + (voly*np.cos(theta))
    
    print("Rotation angle (deg):", np.degrees(theta))
    print("RMS before rotation:", np.sqrt(np.mean(volx**2 + voly**2)))
    print("RMS Y' after rotation:", np.sqrt(np.mean(transformed_y**2)))

    plt.plot(H_field, np.sqrt(transformed_x**2 + transformed_y**2) ,  label=f'{frequency}')
    #plt.plot(current, transformed_y,  label=f'{frequency}')
    #plt.plot(current, np.sqrt(volx**2 + voly**2),  label=f'{frequency}')
    plt.savefig(f"{str(file_name)[:-4]}.png")
    plt.xlabel("current(A)")
    plt.ylabel("vout (uV)")
    plt.legend()
    #plt.show()
    plt.close()
    
    # Initial guess for parameters [A, H_res, delta_H, b, c]
    # H_res_guess = H_field[volx.index[volx == volx.max()][0]]
    # delta_H_guess = H_field[volx.index[volx >= volx.max()/2].to_list()[-1]] - H_field[volx.index[volx >= volx.max()/2].to_list()[1]]
    # c_guess = np.mean(volx)
    # initial_guess = [1, H_res_guess, delta_H_guess, 0, 0]
    # params, covariance = curve_fit(vo_func, H_field, transformed_x, p0=initial_guess)



    # H_fit = np.linspace(min(H_field), max(H_field), 1000)
    # A_fit, H_res, delta_H, b_fit, c_fit = params
    # V_out_fit = vo_func(H_fit, A_fit, H_res, delta_H, b_fit, c_fit)

    
    # plt.scatter(H_fit, V_out_fit, color="red", s=10)
    # plt.plot(H_field, transformed_x,  label=f'{frequency}')
    # plt.plot(H_field, transformed_y,  label=f'{frequency}')
    # plt.close()
    return #{"H_res": H_res, "delta_H": delta_H}

def resonance_freq(H_res, gamma_mu0_over_2pi, M_eff):
    return (gamma_mu0_over_2pi * np.sqrt(H_res * (H_res + M_eff)))

def LineWidth_equ(f, delta_H0, alpha_over_gamma_mu0_over_2pi):
    return delta_H0 + (2 * alpha_over_gamma_mu0_over_2pi) * f

def find_damping(frequencies, Hres, delta_H):

    popt, pcov = curve_fit(resonance_freq, Hres, frequencies, p0=[35198, 0.1])

    gamma_mu0_over_2pi_fit, M_eff_fit = popt

    H_res_fit = np.linspace(min(Hres), max(Hres), 200)
    f_fit = resonance_freq(H_res_fit, gamma_mu0_over_2pi_fit, M_eff_fit)

    plt.scatter(Hres, frequencies, label="Given Data", color="red", s=10)
    plt.plot(H_res_fit, f_fit, label="Fitted Curve", color="blue", linewidth=2)
    plt.xlabel("Hres")
    plt.ylabel("frequencies")
    plt.savefig('HresVsFrequencies.png')
    plt.close()

    popt, pcov = curve_fit(LineWidth_equ, frequencies, delta_H, p0=[1e-3, 1e10])
    delta_H0_fit, alpha_over_gamma_mu0_fit = popt
    f_fit = np.linspace(min(frequencies), max(frequencies), 200)
    delta_H_fit = LineWidth_equ(f_fit, delta_H0_fit, alpha_over_gamma_mu0_fit)
    damping = alpha_over_gamma_mu0_fit * gamma_mu0_over_2pi_fit
    print(f"final_damping  = {damping}")
    plt.scatter(frequencies, delta_H, label="Given Data", color="red", s=10)
    plt.plot(f_fit, delta_H_fit, label="Fitted Curve", color="blue", linewidth=2)
    plt.xlabel("frequency")
    plt.ylabel("Linewidth")
    plt.savefig('freVsLinewidth.png')
    plt.close()

if __name__ == "__main__":
    with open("config.yaml", "r") as file:
        fmr_config_data = yaml.safe_load(file)['FMR_INPUT']
    
    smaple_identity = fmr_config_data['smaple_identity']
    output_folder = fmr_config_data['output_folder']
    start_freq = float(fmr_config_data['microwave_frequencies']['start_frequency'])
    stop_freq = float(fmr_config_data['microwave_frequencies']['stop_frequency'])
    freq_interval = float(fmr_config_data['microwave_frequencies']['frequency_interval'])
    frequencies = np.arange(start_freq, stop_freq, freq_interval)
    print(fmr_config_data)
    H_res = []
    delta_H = []

    for frequency in frequencies:
        file_name = py_fmr(
                        output_folder=output_folder,
                        smaple_identity=smaple_identity,
                        microwave_frequency=frequency,
                        microwave_power=fmr_config_data['power_in_dbm'],
                        curr_range_min=fmr_config_data['magnetic_filed_range']['range_min'],
                        curr_range_max=fmr_config_data['magnetic_filed_range']['range_max'],
                        curr_interval=fmr_config_data['magnetic_filed_range']['filed_interval'],
                        lockin_amp=fmr_config_data['lock_in_amp']['amp'],
                        lockin_freq=fmr_config_data['lock_in_amp']['freq'],
                        lockin_sens=fmr_config_data['lock_in_amp']['sens'],
                        lockin_filter_slope = fmr_config_data['lock_in_amp']['filter_slope'])
        print(file_name)
        # file_name = r"C:\Users\Simulation\Documents\Test\FMR\antidot_PY\antidot_PY_LOR_500uV_FMR_mmWave5.0GHz_power0dBm_lockin_amp4V_freq_113.52.csv"
        data = post_process(file_name, frequency)
        print(file_name)
        # H_res.append(data["H_res"])
        # delta_H.append(data["delta_H"])
    
    # plt.savefig("Hanwie_sample_5E9.png")
    # plt.show()
    # find_damping(fmr_config_data['microwave_frequencies'], H_res, delta_H)

    
                  

    
    
