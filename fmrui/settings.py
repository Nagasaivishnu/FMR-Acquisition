"""Settings model for the FMR acquisition UI.

All run parameters live in one dataclass tree that can be serialised to YAML.
Old-style config.yaml files (with the `smaple_identity` / `magnetic_filed_range`
/ `filed_interval` typos) are still readable -- see `Settings.from_legacy_yaml`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

# SR830 discrete setting tables (value -> what the instrument accepts).
SENSITIVITIES = [
    2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9,
    1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6,
    1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3, 1.0,
]

TIME_CONSTANTS = [
    10e-6, 30e-6, 100e-6, 300e-6, 1e-3, 3e-3, 10e-3, 30e-3, 100e-3, 300e-3,
    1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1e3, 3e3, 10e3, 30e3,
]

FILTER_SLOPES = [6, 12, 18, 24]


def format_sensitivity(value_v: float) -> str:
    """Human tag for a sensitivity, e.g. 500e-6 -> '500uV'.

    Used to build the filename prefix so that the label in the filename is
    always the sensitivity the instrument was actually set to.
    """
    if value_v >= 1.0:
        return f"{value_v:g}V"
    if value_v >= 1e-3:
        return f"{value_v * 1e3:g}mV"
    if value_v >= 1e-6:
        return f"{value_v * 1e6:g}uV"
    return f"{value_v * 1e9:g}nV"


def nearest(value: float, allowed: list) -> float:
    """Snap a requested value to the nearest value the instrument supports."""
    return min(allowed, key=lambda a: abs(a - value))


@dataclass
class InstrumentSettings:
    pna_address: str = "GPIB0::16::INSTR"
    lockin_address: str = "GPIB0::8::INSTR"
    supply_address: str = "GPIB0::6::INSTR"
    gaussmeter_address: str = "COM4"
    supply_compliance_v: float = 14.0
    simulate: bool = False


@dataclass
class LockInSettings:
    amplitude_v: float = 4.0
    reference_hz: float = 113.52
    phase_deg: float = 0.0
    filter_slope_db: int = 24
    time_constant_s: float = 0.3
    sensitivity_v: float = 500e-6

    @property
    def sensitivity_tag(self) -> str:
        return format_sensitivity(self.sensitivity_v)


@dataclass
class SweepSettings:
    start_frequency_hz: float = 2e9
    stop_frequency_hz: float = 20e9
    frequency_step_hz: float = 50e6
    power_dbm: float = 0.0

    current_start_a: float = 15.0
    current_stop_a: float = -15.0
    current_step_a: float = 0.02

    settle_s: float = 0.3
    ramp_step_a: float = 0.25
    ramp_delay_s: float = 0.1


@dataclass
class Settings:
    sample_identity: str = "sample"
    output_folder: str = "run_output"
    instruments: InstrumentSettings = field(default_factory=InstrumentSettings)
    lockin: LockInSettings = field(default_factory=LockInSettings)
    sweep: SweepSettings = field(default_factory=SweepSettings)

    # ---------------------------------------------------------------- naming

    def file_prefix(self) -> str:
        """`<sample>_<sensitivity>` -- the sensitivity tag is derived from the
        value we actually program into the lock-in, so it can never drift out
        of sync with the instrument the way a hand-typed label does."""
        return f"{self.sample_identity}_{self.lockin.sensitivity_tag}"

    def csv_name(self, frequency_hz: float) -> str:
        """Filename compatible with the existing analysis scripts.

        `process_fmr_data.extract_frequency` matches `mmWave([\\d.]+)GHz`, so
        the frequency token must stay in that exact shape.
        """
        lk = self.lockin
        # `round(..., 6)` reproduces the legacy token exactly: 5.0 GHz stays
        # "5.0" and 5.1 GHz stays "5.1" rather than "5.100000000000001".
        ghz = round(frequency_hz / 1e9, 6)
        return (
            f"{self.file_prefix()}_FMR"
            f"_mmWave{ghz}GHz"
            f"_power{lk_fmt(self.sweep.power_dbm)}dBm"
            f"_lockin_amp{lk_fmt(lk.amplitude_v)}V"
            f"_freq_{lk_fmt(lk.reference_hz)}"
            f"_filter_{lk.filter_slope_db}.csv"
        )

    # ----------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        return cls(
            sample_identity=data.get("sample_identity", "sample"),
            output_folder=data.get("output_folder", "run_output"),
            instruments=InstrumentSettings(**(data.get("instruments") or {})),
            lockin=LockInSettings(**(data.get("lockin") or {})),
            sweep=SweepSettings(**(data.get("sweep") or {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if "FMR_INPUT" in data:
            return cls.from_legacy_yaml(data["FMR_INPUT"])
        return cls.from_dict(data)

    @classmethod
    def from_legacy_yaml(cls, block: dict) -> "Settings":
        """Read the original config.yaml, typos and all."""
        freqs = block.get("microwave_frequencies", {})
        fields = block.get("magnetic_filed_range", {})
        lk = block.get("lock_in_amp", {})

        sens_index = lk.get("sens")
        sensitivity = 500e-6
        if isinstance(sens_index, int) and 0 <= sens_index < len(SENSITIVITIES):
            sensitivity = SENSITIVITIES[sens_index]

        # Legacy `time_contant: 300` was an SR830 index, not seconds.
        tc_index = lk.get("time_contant")
        time_constant = 0.3
        if isinstance(tc_index, int) and 0 <= tc_index < len(TIME_CONSTANTS):
            time_constant = TIME_CONSTANTS[tc_index]

        return cls(
            sample_identity=block.get("smaple_identity", "sample"),
            output_folder=block.get("output_folder", "run_output"),
            lockin=LockInSettings(
                amplitude_v=float(lk.get("amp", 4.0)),
                reference_hz=float(lk.get("freq", 113.52)),
                phase_deg=float(lk.get("phase", 0.0)),
                filter_slope_db=int(lk.get("filter_slope", 24)),
                time_constant_s=time_constant,
                sensitivity_v=sensitivity,
            ),
            sweep=SweepSettings(
                start_frequency_hz=float(freqs.get("start_frequency", 2e9)),
                stop_frequency_hz=float(freqs.get("stop_frequency", 20e9)),
                frequency_step_hz=float(freqs.get("frequency_interval", 50e6)),
                power_dbm=float(block.get("power_in_dbm", 0.0)),
                current_start_a=float(fields.get("range_min", 15.0)),
                current_stop_a=float(fields.get("range_max", -15.0)),
                current_step_a=float(fields.get("filed_interval", 0.02)),
            ),
        )

    # ------------------------------------------------------------ validation

    def validate(self) -> list[str]:
        """Return a list of problems; empty list means good to go."""
        problems = []
        s = self.sweep
        if not self.sample_identity.strip():
            problems.append("Sample identity is empty.")
        if s.frequency_step_hz <= 0:
            problems.append("Frequency step must be positive.")
        if s.stop_frequency_hz <= s.start_frequency_hz:
            problems.append("Stop frequency must be above start frequency.")
        if s.current_step_a <= 0:
            problems.append("Field step must be positive (direction is set by start/stop).")
        if s.current_start_a == s.current_stop_a:
            problems.append("Field start and stop are identical.")
        if abs(s.current_start_a) > 20 or abs(s.current_stop_a) > 20:
            problems.append("Current outside the +/-20 A range of the Kepco BOP36-12.")
        if s.settle_s < self.lockin.time_constant_s:
            problems.append(
                f"Settle time ({s.settle_s} s) is shorter than the lock-in time constant "
                f"({self.lockin.time_constant_s} s) -- readings will lag the field."
            )
        return problems


def lk_fmt(value: float) -> str:
    """Format a number the way the legacy filenames did (no trailing .0)."""
    return f"{value:g}"


def write_metadata(path: Path, settings: Settings, extra: dict) -> None:
    """Sidecar JSON next to the run.

    The CSV itself keeps exactly the four legacy columns and no comment header,
    so `pandas.read_csv` in the existing analysis scripts still works untouched.
    Everything that used to be unrecorded (sensitivity, time constant, settle
    time, calibration in force) goes here instead.
    """
    payload = {"settings": settings.to_dict(), **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
