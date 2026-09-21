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


def frequency_spectrum():
    gaussmter = LakeShore425('COM4')
    lockinamp = SR830('GPIB0::8::INSTR')
    powersupply = KepcoBOP3612('GPIB0::6::INSTR')
    networkan = NetworkAnalyser()
    
    powersupply.operating_mode = 'CURR'
    powersupply.output_enabled = True
    powersupply.voltage_setpoint = 14
    powersupply.current_setpoint = 1
    time.sleep(5)
    lockinamp.sine_voltage = 0.2
    lockinamp.frequency = 113.52
    lockinamp.phase = 0

    frequencies = np.arange(2E9, 10E9, 10E6)
    volx = []
    voly = []

    for freq in frequencies:
        networkan.generate_signal(freq, 15)
        print(freq)
        time.sleep(2)
        volx.append(lockinamp.x)
        voly.append(lockinamp.y)
    
    plt.plot(frequencies, volx)
    plt.show()


if __name__ == "__main__":
    frequency_spectrum()




