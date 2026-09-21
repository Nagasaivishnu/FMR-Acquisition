from pymeasure.instruments.kepco import KepcoBOP3612
from pymeasure.instruments.lakeshore import LakeShore425
from pymeasure.instruments.srs import SR830
from pna import NetworkAnalyser
import time

def set_field():
    gaussmter = LakeShore425('COM4')
    lockinamp = SR830('GPIB0::8::INSTR')
    powersupply = KepcoBOP3612('GPIB0::6::INSTR')
    #networkan = NetworkAnalyser()
    i2 =  0
    powersupply.operating_mode = 'CURR'
    powersupply.output_enabled = True
    powersupply.voltage_setpoint = 20
    powersupply.current_setpoint = 1
    for k in range(5):
        print(gaussmter.field)
        time.sleep(1)  # Wait for the current to stabilize


   # time.sleep(5)

    curr =  20
    powersupply.current_setpoint = curr
    time.sleep(5)
    while curr > i2:
        curr -= 0.05  # Decrease current gradually
        powersupply.current_setpoint = curr
        print(round(curr,3), gaussmter.field)
        #print(gaussmter.field)
        time.sleep(0.1)  # Wait for the current to stabilize

    # while i > 0:
    #     i -= 0.1  # Decrease current gradually
    #     powersupply.current_setpoint = i
    #     print(i)
    #     print(gaussmter.field)
    #     time.sleep(1)  # Wait for the current to stabilize

    time.sleep(5)
    print(gaussmter.field)
    time.sleep(5)
    print(gaussmter.field)
    powersupply.output_enabled = False
    print("please remove the sample")
    time.sleep(5*60)
    
    
    



if __name__ == "__main__":
    set_field()