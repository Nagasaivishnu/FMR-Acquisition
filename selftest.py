"""Headless check of the acquisition path -- no GUI, no hardware.

    python selftest.py

Runs a tiny simulated sweep, then verifies that the files it produced are
readable by the existing analysis scripts (same four columns, same filename
pattern that process_fmr_data.extract_frequency expects).
"""

import queue
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fmrui.acquisition import SweepWorker, field_setpoints, frequency_list
from fmrui.fieldtools import Calibration, CalibrationWorker, save_as_active
from fmrui.instruments import make_rig
from fmrui.settings import Settings

FREQ_RE = re.compile(r"mmWave([\d.]+)GHz")  # copied from process_fmr_data.py

failures = []


def check(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'  -- ' + detail if detail else ''}")
    if not condition:
        failures.append(name)


def drain(events):
    out = []
    while not events.empty():
        out.append(events.get())
    return out


print("Grid construction")
sp = field_setpoints(15.0, -15.0, 0.02)
check("reverse sweep is inclusive at both ends", sp[0] == 15.0 and sp[-1] == -15.0)
check("point count matches the legacy 1501", len(sp) == 1501, f"{len(sp)} points")
check("no floating-point drift in the step",
      abs(abs(sp[1] - sp[0]) - 0.02) < 1e-12)
fr = frequency_list(2e9, 20e9, 50e6)
check("2-20 GHz at 50 MHz gives 360 frequencies", len(fr) == 360, f"{len(fr)}")

print("\nSimulated sweep")
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    st = Settings()
    st.sample_identity = "selftest"
    st.output_folder = "out"
    st.instruments.simulate = True
    st.sweep.start_frequency_hz = 5e9
    st.sweep.stop_frequency_hz = 5.2e9
    st.sweep.frequency_step_hz = 100e6
    st.sweep.current_start_a = 6.0
    st.sweep.current_stop_a = -6.0
    st.sweep.current_step_a = 0.5
    st.sweep.settle_s = 0.0
    st.sweep.ramp_delay_s = 0.0
    st.lockin.sensitivity_v = 500e-6

    rig = make_rig(st.instruments)
    rig.connect()
    events = queue.Queue()
    worker = SweepWorker(st, rig, events, base)
    worker.start()
    worker.join(timeout=60)

    kinds = [k for k, _ in drain(events)]
    check("worker reported finished", "finished" in kinds)
    check("worker returned to idle", "idle" in kinds)

    csvs = sorted((base / "out").glob("*FMR*.csv"))
    check("one CSV per frequency", len(csvs) == 2, f"{len(csvs)} files")
    check("PNG saved alongside each CSV",
          all(c.with_suffix(".png").exists() for c in csvs))
    check("run metadata sidecar written",
          len(list((base / "out").glob("*_run_metadata.json"))) == 1)

    if csvs:
        name = csvs[0].name
        m = FREQ_RE.search(name)
        check("filename parses with the existing frequency regex",
              m is not None, name)
        check("sensitivity tag matches the applied sensitivity",
              "_500uV_" in name, name)

        import pandas as pd
        df = pd.read_csv(csvs[0])
        check("plain read_csv works (no comment header)", len(df) > 0)
        check("legacy column names preserved",
              list(df.columns) == ["Current", "field", "voltageX", "voltageY"],
              str(list(df.columns)))
        check("row count matches the setpoint grid", len(df) == 25, f"{len(df)} rows")
        check("first logged current IS the first setpoint (off-by-one fixed)",
              df["Current"].iloc[0] == 6.0, f"got {df['Current'].iloc[0]}")
        check("last logged current IS the last setpoint",
              df["Current"].iloc[-1] == -6.0, f"got {df['Current'].iloc[-1]}")
        check("magnet left at zero after the run", rig.read_current() == 0.0)

    print("\nCalibration worker")
    events = queue.Queue()
    cal_worker = CalibrationWorker(rig, events, base, -4.0, 4.0, 1.0, 0.0, 14.0)
    cal_worker.start()
    cal_worker.join(timeout=60)
    payloads = {k: v for k, v in drain(events)}
    check("calibration completed", "cal_done" in payloads)
    if "cal_done" in payloads:
        cal = payloads["cal_done"]
        check("fitted slope is close to the simulator's 0.0267 T/A",
              abs(cal.slope - 0.0267) < 5e-4, f"{cal.slope:.6g}")
        check("fit quality is sane", cal.r_squared > 0.999, f"R2={cal.r_squared:.6f}")
        check("a fresh run does NOT replace the active calibration",
              not (base / "magnet_calibration.json").exists())
        check("run archived in calibrations/ (csv + json + png)",
              all(len(list((base / "calibrations").glob(f"calibration_*.{e}"))) == 1
                  for e in ("csv", "json", "png")))
    cal_csv = sorted((base / "calibrations").glob("calibration_*.csv"))
    if cal_csv:
        first_line = cal_csv[0].read_text().splitlines()[0]
        check("calibration CSV header is its own line",
              first_line == "AppliedCurrent,MeasuredCurrent,field", first_line)
        again = Calibration.from_csv(cal_csv[0])
        check("re-fitting the archived CSV reproduces the run",
              abs(again.slope - cal.slope) < 1e-12)

    print("\nCalibration save / load")
    first = Calibration.from_points([0, 1, 2, 3], [0.0, 0.025, 0.05, 0.075],
                                    note="first")
    backup = save_as_active(first, base)
    active = base / "magnet_calibration.json"
    check("save_as_active writes the active file", active.exists())
    check("no backup when nothing was replaced", backup is None)
    reloaded = Calibration.load(active)
    check("active file reloads with its points",
          abs(reloaded.slope - 0.025) < 1e-12 and len(reloaded.currents) == 4)

    second = Calibration.from_points([0, 1, 2, 3], [0.0, 0.027, 0.054, 0.081])
    backup = save_as_active(second, base)
    check("replacing keeps the previous file in calibrations/",
          backup is not None and backup.exists()
          and abs(Calibration.load(backup).slope - 0.025) < 1e-12)
    check("new calibration is now active",
          abs(Calibration.load(active).slope - 0.027) < 1e-12)
    check("comparison text reports the change",
          "+8.00 %" in second.compare(first) and "+20.00 mT" in second.compare(first), second.compare(first))

    old_json = base / "old_style.json"
    old_json.write_text('{"slope": 0.0241, "intercept": -0.0006, "r_squared": 0.99,'
                        ' "n_points": 10, "current_range_a": [5, 10],'
                        ' "created": "2025-07-14T12:00:00", "note": "x"}')
    old = Calibration.from_file(old_json)
    check("older JSON without raw points still loads",
          abs(old.slope - 0.0241) < 1e-12 and len(old.currents) == 2)

    glued = base / "calibrated_data_legacy.csv"
    glued.write_text("field,AppliedCurrent,MeasureCurrent-0.0013, 0, -0.0414\n"
                     "0.0254, 1.0, 1.01\n0.0521, 2.0, 1.98\n0.0788, 3.0, 3.02\n")
    leg = Calibration.from_file(glued)
    check("legacy CSV with glued header: first row recovered",
          leg.n_points == 4 and leg.currents[0] == 0.0 and leg.fields[0] == -0.0013,
          f"{leg.n_points} pts, first ({leg.currents[0]}, {leg.fields[0]})")
    check("legacy CSV columns mapped by name (field is col 0)",
          abs(leg.slope - 0.02674) < 5e-4, f"{leg.slope:.5f}")

    missing = Calibration.load(base / "nope.json")
    check("missing active file falls back to the default estimate",
          not missing.is_measured)

print("\nSettings round-trip")
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "cfg.yaml"
    original = Settings()
    original.sample_identity = "round_trip"
    original.save(p)
    check("saved settings reload identically",
          Settings.load(p).to_dict() == original.to_dict())

    legacy = Path(tmp) / "legacy.yaml"
    legacy.write_text(
        "FMR_INPUT:\n"
        "  output_folder: \"Py_vishnu_Antidot_reverse_sweep1\"\n"
        "  smaple_identity: \"Py_vishnu_Antidot_reverse_sweep_500uV\"\n"
        "  microwave_frequencies:\n"
        "    start_frequency: 2E9\n    stop_frequency: 20E9\n"
        "    frequency_interval: 50E6\n"
        "  power_in_dbm: 0\n"
        "  magnetic_filed_range:\n"
        "    range_min: 15\n    range_max: -15\n    filed_interval: 0.02\n"
        "  lock_in_amp:\n    phase: 0\n    freq: 113.52\n    amp: 4\n"
        "    sens: 15\n    filter_slope: 24\n")
    old = Settings.load(legacy)
    check("legacy config.yaml still loads (typo keys and all)",
          old.sample_identity == "Py_vishnu_Antidot_reverse_sweep_500uV")
    check("legacy sens index 15 maps to 200 uV",
          abs(old.lockin.sensitivity_v - 200e-6) < 1e-12,
          f"{old.lockin.sensitivity_v}")

print("\nData folder resolution")
import os
from fmrui import paths
saved_local, saved_env = paths.LOCAL_CONFIG, os.environ.pop(paths.ENV_VAR, None)
with tempfile.TemporaryDirectory() as tmp:
    paths.LOCAL_CONFIG = Path(tmp) / "local_config.yaml"
    d, src = paths.resolve_data_dir()
    check("falls back to <repo>/data", d == paths.DEFAULT_DATA_DIR and src == "default")
    paths.save_data_dir(Path(tmp) / "lab")
    d, src = paths.resolve_data_dir()
    check("remembers the folder picked in the UI",
          d == Path(tmp) / "lab" and src == "local_config.yaml")
    os.environ[paths.ENV_VAR] = str(Path(tmp) / "env")
    d, src = paths.resolve_data_dir()
    check("environment variable beats local_config", d == Path(tmp) / "env")
    d, src = paths.resolve_data_dir(str(Path(tmp) / "cli"))
    check("--data-dir beats everything", d == Path(tmp) / "cli" and src == "--data-dir")
    os.environ.pop(paths.ENV_VAR)
paths.LOCAL_CONFIG = saved_local
if saved_env is not None:
    os.environ[paths.ENV_VAR] = saved_env

print("\nValidation warnings")
bad = Settings()
bad.sweep.settle_s = 0.01
bad.lockin.time_constant_s = 0.3
bad.sweep.current_start_a = 30.0
problems = bad.validate()
check("settle shorter than time constant is flagged",
      any("time constant" in p for p in problems))
check("out-of-range current is flagged", any("+/-20 A" in p for p in problems))

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("All checks passed.")
