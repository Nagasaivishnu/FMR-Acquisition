import pyvisa

# rm = pyvisa.ResourceManager()
# lockin = rm.open_resource('GPIB0::8::INSTR')

# time_constant = lockin.query("OFLT?")
# print(f"Current time constant index: {time_constant}")
# lockin.write("OFLT 9")
# new_time_constant = lockin.query("OFLT?")
# print(f"New time constant index: {new_time_constant}")
# lockin.write("FREQ 475*1000000")
# print(lockin.query("FREQ?"))
# lockin.close()


class LockInAmp:
    def __init__(self):
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource('GPIB0::8::INSTR')
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"
        print(self.inst.query("*IDN?"))
    
    def set_ref_freq(self, frequency):
        self.inst.write("FMOD 1")
        self.inst.write(f"FREQ {frequency}")
    
    def set_amp(self, amp):
        self.inst.write(f"SLVL {amp}")

    def set_time_const(self, time_constant_number=8):
        self.inst.write(f"OFLT {time_constant_number}")
    
    def get_outputX(self):
        self.inst.write("OUTX 1")
        return float(self.inst.query("OUTP? 1"))
    
    def get_outputY(self):
        self.inst.write("OUTY 1")
        return float(self.inst.query("OUTP? 1"))
        