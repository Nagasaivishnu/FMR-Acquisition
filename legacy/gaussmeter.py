from lakeshore import Model425
import pyvisa

class GaussMeter:
    def __init__(self):
        self.inst = Model425()
        self.inst.command("MODE DC")
    
    def read_field(self):
        return int(float(self.inst.query("RDGFIELD?")) * 10000)


