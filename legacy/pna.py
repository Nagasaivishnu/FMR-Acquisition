import pyvisa
import matplotlib.pyplot as plt
import numpy as np
class NetworkAnalyser:
    def __init__(self):
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource("GPIB0::16::INSTR")
        self.inst.write_termination = "\r\n"
        self.inst.read_termination = "\r\n"
        self.inst.write("OUTP ON")
        print(self.inst.query("*IDN?"))
    
    def generate_signal(self, frequency, power):
        if self.inst is None:
            print("Instrument not connected.")
            return
        
        self.inst.write('*CLS')

        self.inst.write(f"SENS:FREQ:CENT {frequency}Hz")
        self.inst.write(f"SENS:FREQ:SPAN 0Hz") 
        self.inst.write(f"SOUR:POW {power} dBm")  # Set power level
        self.inst.write("OUTP ON")  # Enable RF output
        # error = self.inst.query('SYST:ERR?')
        # print(f"Instrument error: {error}")
    
    def generate_signal_port2(self, frequency, power):
        """Generate signal from Port 2 of the network analyzer."""
        if self.inst is None:
            print("Instrument not connected.")
            return
        
        self.inst.write('*CLS')
        
        self.inst.write(f"SENS:FREQ:CENT {frequency}Hz")
        self.inst.write(f"SENS:FREQ:SPAN 0Hz")
        self.inst.write(f"SOUR2:POW {power} dBm")  # Set power level for Port 2
        self.inst.write("OUTP2 ON")  # Enable RF output on Port 2
        error = self.inst.query('SYST:ERR?')
        print(f"Port 2 Signal Generated - Frequency: {frequency}Hz, Power: {power}dBm")
        print(f"Instrument error: {error}")
        
    
    def get_s22(self, frequency):
        # self.inst.write('SYST:REM')
        self.inst.write('*CLS')
        
        self.inst.write("SENS:SWE:POIN 2")

        self.inst.write('SOUR:POW 5 dBm')
        existing_meas = self.inst.query("CALC:PAR:CAT?")
        if "S22_MEAS" in existing_meas:
            self.inst.write('CALC:PAR:SEL "S22_MEAS"')  # Select existing
        else:
            self.inst.write('CALC:PAR:DEF "S22_MEAS", S22')  # Define
            self.inst.write('CALC:PAR:SEL "S22_MEAS"')
        self.inst.write("INIT:CONT OFF")
        self.inst.write("TRIG:SOUR EXT")
        self.inst.write('INIT:IMM;*wai')
        data = self.inst.query('CALC:DATA? SDATA')
        error = self.inst.query('SYST:ERR?')
        print(f"Instrument error: {error}")

        return [float(x) for x in data.split(',')]
        # data = np.array([float(x) for x in data.split(',')])

        # # Check the length of the data
        # print(f"Number of data points: {len(data)}")

        # # Separate the real and imaginary parts
        # real_part = data[::2]
        # imaginary_part = data[1::2]

        # # Calculate the magnitude and phase
        # magnitude = np.sqrt(real_part**2 + imaginary_part**2)
        # phase = np.arctan2(imaginary_part, real_part)

        # # Plot the magnitude
        # plt.plot(magnitude, label='Magnitude')
        # plt.xlabel('Frequency Point')
        # plt.ylabel('Magnitude')
        # plt.legend()
        # plt.show()

