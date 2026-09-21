"""Instrument layer for the FMR rig.

One class owns every instrument, so addresses are configured in exactly one
place (the old code had the gaussmeter on COM4 in FMR.py and COM5 in
calibrate_power_supply, and three parallel driver wrappers).

`simulate=True` swaps in a synthetic rig so the whole UI can be exercised on a
laptop with no GPIB hardware attached.
"""

from __future__ import annotations

import math
import random
import time

from .settings import (
    FILTER_SLOPES,
    SENSITIVITIES,
    TIME_CONSTANTS,
    InstrumentSettings,
    LockInSettings,
    nearest,
)

# Kepco BOP36-12: +/-12 A continuous, +/-20 A peak. Refuse anything past this.
MAX_CURRENT_A = 20.0


class InstrumentError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Real hardware
# --------------------------------------------------------------------------


class NetworkAnalyser:
    """Agilent/Keysight PNA used as a fixed-frequency CW source."""

    def __init__(self, address: str):
        import pyvisa

        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(address)
        self.inst.write_termination = "\r\n"
        self.inst.read_termination = "\r\n"
        self.idn = self.inst.query("*IDN?")

    def set_signal(self, frequency_hz: float, power_dbm: float) -> None:
        self.inst.write("*CLS")
        self.inst.write(f"SENS:FREQ:CENT {frequency_hz}Hz")
        self.inst.write("SENS:FREQ:SPAN 0Hz")
        self.inst.write(f"SOUR:POW {power_dbm} dBm")
        self.inst.write("OUTP ON")

    def output(self, enabled: bool) -> None:
        self.inst.write(f"OUTP {'ON' if enabled else 'OFF'}")

    def close(self) -> None:
        try:
            self.inst.write("OUTP OFF")
            self.inst.close()
        except Exception:
            pass


class Rig:
    """PNA + SR830 lock-in + Kepco supply + LakeShore gaussmeter."""

    def __init__(self, cfg: InstrumentSettings):
        self.cfg = cfg
        self.pna = None
        self.lockin = None
        self.supply = None
        self.gauss = None
        self.identities: dict[str, str] = {}
        self._current_a = 0.0

    # ------------------------------------------------------------- lifecycle

    def connect(self) -> dict[str, str]:
        from pymeasure.instruments.kepco import KepcoBOP3612
        from pymeasure.instruments.lakeshore import LakeShore425
        from pymeasure.instruments.srs import SR830

        self.gauss = LakeShore425(self.cfg.gaussmeter_address)
        self.gauss.unit = "T"
        self.lockin = SR830(self.cfg.lockin_address)
        self.supply = KepcoBOP3612(self.cfg.supply_address)
        self.pna = NetworkAnalyser(self.cfg.pna_address)

        self.identities = {
            "PNA": self.pna.idn,
            "Lock-in": _safe_id(self.lockin),
            "Supply": _safe_id(self.supply),
            "Gaussmeter": _safe_id(self.gauss),
        }
        return self.identities

    def close(self) -> None:
        # Never leave the magnet energised on the way out.
        try:
            self.safe_shutdown()
        except Exception:
            pass
        if self.pna is not None:
            self.pna.close()
        for inst in (self.lockin, self.supply, self.gauss):
            try:
                if inst is not None and hasattr(inst, "shutdown"):
                    inst.shutdown()
            except Exception:
                pass

    # ------------------------------------------------------------- lock-in

    def configure_lockin(self, lk: LockInSettings) -> LockInSettings:
        """Program the lock-in and return the settings actually applied.

        Discrete settings are snapped to the nearest supported value and handed
        back, so the caller can show and record what the box is really doing.
        Notably `sensitivity` is applied here -- in the old code that line was
        commented out while the filename still claimed a value.
        """
        applied = LockInSettings(
            amplitude_v=lk.amplitude_v,
            reference_hz=lk.reference_hz,
            phase_deg=lk.phase_deg,
            filter_slope_db=int(nearest(lk.filter_slope_db, FILTER_SLOPES)),
            time_constant_s=nearest(lk.time_constant_s, TIME_CONSTANTS),
            sensitivity_v=nearest(lk.sensitivity_v, SENSITIVITIES),
        )
        self.lockin.sine_voltage = applied.amplitude_v
        self.lockin.frequency = applied.reference_hz
        self.lockin.phase = applied.phase_deg
        self.lockin.filter_slope = applied.filter_slope_db
        self.lockin.time_constant = applied.time_constant_s
        self.lockin.sensitivity = applied.sensitivity_v
        return applied

    def read_xy(self) -> tuple[float, float]:
        """X and Y from a single instrument snapshot.

        Two separate `OUTP?` queries sample the signal a few hundred
        milliseconds apart; during a moving field sweep that smears the phase.
        SNAP returns both from one conversion.
        """
        try:
            x, y = self.lockin.snap("X", "Y")
            return float(x), float(y)
        except Exception:
            return float(self.lockin.x), float(self.lockin.y)

    # ------------------------------------------------------------ microwave

    def set_microwave(self, frequency_hz: float, power_dbm: float) -> None:
        self.pna.set_signal(frequency_hz, power_dbm)

    def rf_output(self, enabled: bool) -> None:
        self.pna.output(enabled)

    # -------------------------------------------------------------- magnet

    def enable_supply(self, compliance_v: float) -> None:
        self.supply.operating_mode = "CURR"
        self.supply.voltage_setpoint = compliance_v
        self.supply.current_setpoint = 0.0
        self.supply.output_enabled = True
        self._current_a = 0.0

    def set_current(self, amps: float) -> None:
        if abs(amps) > MAX_CURRENT_A:
            raise InstrumentError(
                f"Refusing {amps:.3f} A -- outside the +/-{MAX_CURRENT_A:g} A limit."
            )
        self.supply.current_setpoint = amps
        self._current_a = amps

    def read_current(self) -> float:
        return float(self.supply.current)

    def read_field(self) -> float:
        return float(self.gauss.field)

    def ramp_current(self, target_a: float, step_a: float, delay_s: float,
                     should_stop=None, on_step=None) -> None:
        """Walk the magnet current to `target_a` in bounded steps.

        The old code jumped straight from 0 A to the sweep start (15 A), which
        is a 15 A step into an inductive load.
        """
        step_a = max(abs(step_a), 1e-6)
        while abs(target_a - self._current_a) > step_a:
            if should_stop is not None and should_stop():
                return
            direction = 1.0 if target_a > self._current_a else -1.0
            self.set_current(self._current_a + direction * step_a)
            if on_step is not None:
                on_step(self._current_a)
            time.sleep(delay_s)
        self.set_current(target_a)
        if on_step is not None:
            on_step(self._current_a)
        time.sleep(delay_s)

    def safe_shutdown(self) -> None:
        """Ramp the magnet down and kill the RF. Always safe to call twice."""
        if self.supply is not None:
            try:
                self.ramp_current(0.0, 0.5, 0.05)
                self.supply.output_enabled = False
            except Exception:
                pass
        if self.pna is not None:
            try:
                self.pna.output(False)
            except Exception:
                pass


def _safe_id(instrument) -> str:
    try:
        return str(instrument.id)
    except Exception:
        return "(no *IDN? response)"


# --------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------


class SimulatedRig(Rig):
    """Synthetic rig: Kittel resonance + derivative-Lorentzian lineshape.

    Lets you lay out a run, check filenames and watch the live plot without
    touching the lab PC.
    """

    GAMMA_GHZ_PER_T = 30.0
    M_EFF_T = 0.85
    LINEWIDTH_T = 0.004
    AMP_TO_TESLA = 0.0267

    def __init__(self, cfg: InstrumentSettings):
        super().__init__(cfg)
        self._frequency_hz = 5e9
        self._power_dbm = 0.0
        self._sensitivity = 500e-6

    def connect(self) -> dict[str, str]:
        self.identities = {
            "PNA": "SIMULATED PNA",
            "Lock-in": "SIMULATED SR830",
            "Supply": "SIMULATED Kepco BOP36-12",
            "Gaussmeter": "SIMULATED LakeShore 425",
        }
        self.pna = self.lockin = self.supply = self.gauss = object()
        return self.identities

    def close(self) -> None:
        self._current_a = 0.0

    def configure_lockin(self, lk: LockInSettings) -> LockInSettings:
        applied = LockInSettings(
            amplitude_v=lk.amplitude_v,
            reference_hz=lk.reference_hz,
            phase_deg=lk.phase_deg,
            filter_slope_db=int(nearest(lk.filter_slope_db, FILTER_SLOPES)),
            time_constant_s=nearest(lk.time_constant_s, TIME_CONSTANTS),
            sensitivity_v=nearest(lk.sensitivity_v, SENSITIVITIES),
        )
        self._sensitivity = applied.sensitivity_v
        return applied

    def set_microwave(self, frequency_hz: float, power_dbm: float) -> None:
        self._frequency_hz = frequency_hz
        self._power_dbm = power_dbm

    def rf_output(self, enabled: bool) -> None:
        pass

    def enable_supply(self, compliance_v: float) -> None:
        self._current_a = 0.0

    def set_current(self, amps: float) -> None:
        if abs(amps) > MAX_CURRENT_A:
            raise InstrumentError(f"Refusing {amps:.3f} A -- outside safe range.")
        self._current_a = amps

    def read_current(self) -> float:
        return self._current_a

    def read_field(self) -> float:
        return self._current_a * self.AMP_TO_TESLA + random.gauss(0, 2e-5)

    def _resonance_field(self) -> float:
        f = self._frequency_hz / 1e9
        m = self.M_EFF_T
        inner = (m / 2) ** 2 + (f / self.GAMMA_GHZ_PER_T) ** 2
        return max(math.sqrt(inner) - m / 2, 0.0)

    def read_xy(self) -> tuple[float, float]:
        h = self.read_field()
        h_res = self._resonance_field()
        w = self.LINEWIDTH_T
        d = abs(h) - h_res
        lineshape = -2 * w ** 2 * d / ((d ** 2 + w ** 2) ** 2)
        scale = self._sensitivity * 1e-4
        noise = self._sensitivity * 2e-4
        x = 1.1e-5 + lineshape * scale + random.gauss(0, noise)
        y = -6.3e-6 + 0.3 * lineshape * scale + random.gauss(0, noise)
        return x, y

    def safe_shutdown(self) -> None:
        self._current_a = 0.0


def make_rig(cfg: InstrumentSettings) -> Rig:
    return SimulatedRig(cfg) if cfg.simulate else Rig(cfg)
