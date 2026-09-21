import pyvisa
import time

class PowerSupply:
    def __init__(self):
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource('GPIB0::6::INSTR')
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"
        self.inst.write("SYST:REM ON")
        self.inst.write("OUTP ON")
        self.inst.write("FUNC:MODE VOLT")
        print(self.inst.query("*IDN?"))
        
    
    def set_voltage(self, voltage):
        self.inst.write(f'VOLT {voltage}')
    
    def set_current(self, current):
        self.inst.write(f'CURR {current}')
        time.sleep(1.5)

    def read_voltage(self):
        return self.inst.query("MEAS:VOLT?")
    
    def read_current(self):
        return self.inst.query("MEAS:CURR?")