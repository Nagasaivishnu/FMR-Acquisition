import matplotlib.pyplot as plt
import yaml
from FMR import post_process, find_damping


if __name__ == "__main__":
    with open("config.yaml", "r") as file:
        fmr_config_data = yaml.safe_load(file)['FMR_INPUT']
    file_names = ["FMR_mmWave4E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave4.5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave5.5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave6E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave6.5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave7E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave7.5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave8E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave9E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave10E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",
                  "FMR_mmWave12E9_power10dBm_lockin_amp0.25V_freq_113.52.csv",]

    frequencies = [4, 4.5, 5.5, 6, 6.5, 7, 7.5, 8, 9, 10, 12]
    frequencies_int = [4E9, 4.5E9, 5.5E9, 6E9, 6.5E9, 7E9, 7.5E9, 8E9, 9E9, 10E9, 12E9]
    H_res = []
    delta_H = []
    for frequency in frequencies:
        file_name =f"FMR_mmWave{frequency}E9_power10dBm_lockin_amp0.25V_freq_113.52.csv"
        # file_name = "FMR_mmWave5E9_power10dBm_lockin_amp0.25V_freq_113.52.csv"
        data = post_process(file_name, frequency, float(fmr_config_data['gyromagnetic_ratio']))

        H_res.append(data["H_res"])
        delta_H.append(data["delta_H"])
    plt.close()

    with open("py_film_hres_deltah.csv", "w") as file:
        file.write("frequency,Hres,linewidth\n")
        for i in range(len(frequencies)):
            file.write(f"{frequencies[i]},{H_res[i]},{delta_H[i]}\n")

    find_damping(frequencies, H_res, delta_H)