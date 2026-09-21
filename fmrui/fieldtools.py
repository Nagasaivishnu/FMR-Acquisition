"""Magnet utilities: set-field, degauss, ramp-down and current-to-field
calibration.

Replaces the old `set_field.py` and the extensionless `calibrate_power_supply`
script, with the coefficients stored in a file instead of pasted into the
source as a literal.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .instruments import Rig

CALIBRATION_FILE = "magnet_calibration.json"   # the active calibration
HISTORY_DIR = "calibrations"                    # every run and replaced file


@dataclass
class Calibration:
    """field_T = slope * current_A + intercept.

    The raw points are kept with the fit so any saved calibration can be
    re-plotted and compared later.
    """

    slope: float = 0.0267
    intercept: float = 0.0
    r_squared: float = 0.0
    n_points: int = 0
    current_range_a: tuple = (0.0, 0.0)
    created: str = ""
    note: str = "default estimate -- run or load a calibration to replace"
    source: str = ""
    currents: list = field(default_factory=list)
    fields: list = field(default_factory=list)

    # ------------------------------------------------------------ conversion

    @property
    def is_measured(self) -> bool:
        return bool(self.created)

    def current_for_field(self, field_t: float) -> float:
        if self.slope == 0:
            raise ValueError("Calibration slope is zero.")
        return (field_t - self.intercept) / self.slope

    def field_for_current(self, current_a: float) -> float:
        return self.slope * current_a + self.intercept

    # ------------------------------------------------------------- building

    @classmethod
    def from_points(cls, currents, fields, source: str = "", created: str = "",
                    note: str = "") -> "Calibration":
        cur = np.asarray(currents, dtype=float)
        fld = np.asarray(fields, dtype=float)
        ok = np.isfinite(cur) & np.isfinite(fld)
        cur, fld = cur[ok], fld[ok]
        if len(cur) < 3 or np.ptp(cur) == 0:
            raise ValueError("Need at least 3 points spanning more than one current.")
        slope, intercept = np.polyfit(cur, fld, 1)
        predicted = slope * cur + intercept
        ss_res = float(np.sum((fld - predicted) ** 2))
        ss_tot = float(np.sum((fld - fld.mean()) ** 2))
        return cls(
            slope=float(slope), intercept=float(intercept),
            r_squared=1 - ss_res / ss_tot if ss_tot else 0.0,
            n_points=int(len(cur)),
            current_range_a=(float(cur.min()), float(cur.max())),
            created=created or datetime.now().isoformat(timespec="seconds"),
            note=note, source=source,
            currents=[float(c) for c in cur], fields=[float(f) for f in fld],
        )

    @classmethod
    def from_csv(cls, path: Path) -> "Calibration":
        """Fit a calibration from a CSV of current and field.

        Reads the new format (`AppliedCurrent,MeasuredCurrent,field`) and the
        old `calibrated_data_*.csv` files, including the ones whose header has
        no line ending and swallowed the first data row.
        """
        path = Path(path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise ValueError(f"{path.name} is empty.")
        first, _, rest = text.partition("\n")

        # Split "field,AppliedCurrent,MeasureCurrent-0.0013, 0, -0.04" into the
        # header names and whatever numeric row got glued onto the end.
        m = re.match(r"^\s*((?:[A-Za-z_][A-Za-z_ ]*,\s*)*[A-Za-z_][A-Za-z_]*)(.*)$", first)
        if not m:
            raise ValueError(f"{path.name}: no header row found.")
        names = [n.strip().lower() for n in m.group(1).split(",")]
        glued = m.group(2).strip().lstrip(",").strip()
        lines = ([glued] if glued else []) + rest.splitlines()

        def column(*candidates):
            for c in candidates:
                if c in names:
                    return names.index(c)
            return None

        i_cur = column("appliedcurrent", "current", "measuredcurrent", "measurecurrent")
        i_fld = column("field", "field_t", "b")
        if i_cur is None or i_fld is None:
            raise ValueError(f"{path.name}: need a current column and a field column, "
                             f"found {names}.")

        currents, fields = [], []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            try:
                currents.append(float(parts[i_cur]))
                fields.append(float(parts[i_fld]))
            except (IndexError, ValueError):
                continue  # blank or malformed row

        return cls.from_points(currents, fields, source=str(path),
                               created=_date_for(path), note=f"fitted from {path.name}")

    @classmethod
    def from_file(cls, path: Path) -> "Calibration":
        """Load a calibration JSON, or fit one from a CSV."""
        path = Path(path)
        if path.suffix.lower() == ".csv":
            return cls.from_csv(path)
        cal = cls.load(path)
        if not cal.source:
            cal.source = str(path)
        return cal

    # ---------------------------------------------------------- persistence

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["current_range_a"] = list(self.current_range_a)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        """Read a calibration JSON. Missing file -> default estimate."""
        if not Path(path).exists():
            return cls()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        data["current_range_a"] = tuple(data.get("current_range_a", (0.0, 0.0)))
        cal = cls(**data)
        # Older files have no points; synthesise the fitted line so it plots.
        if not cal.currents and cal.is_measured and cal.current_range_a[0] != cal.current_range_a[1]:
            lo, hi = cal.current_range_a
            cal.currents = [lo, hi]
            cal.fields = [cal.field_for_current(lo), cal.field_for_current(hi)]
        return cal

    # ------------------------------------------------------------- display

    def describe(self) -> str:
        if not self.is_measured:
            return f"{self.slope:.6g} T/A (default estimate, not measured)"
        return (f"{self.slope:.6g} T/A, offset {self.intercept:+.4g} T "
                f"| R2={self.r_squared:.5f} | {self.n_points} pts "
                f"| {self.created[:10]}")

    def compare(self, other: "Calibration", at_current_a: float = 10.0) -> str:
        """How much would switching from `other` to `self` change the field?"""
        if other.slope == 0:
            return ""
        d_slope = 100.0 * (self.slope - other.slope) / other.slope
        d_field = (self.field_for_current(at_current_a)
                   - other.field_for_current(at_current_a)) * 1e3
        return (f"vs active  slope {d_slope:+.2f} %\n"
                f"           {d_field:+.2f} mT at {at_current_a:g} A")


def _date_for(path: Path) -> str:
    """When was this calibration measured?

    Old files carry the date in the name as DDMMYYYY
    (calibrated_data_14072025_high_field.csv); new ones as YYYYMMDD_HHMMSS
    (calibration_20260921_071820.csv). Copying a file resets its modification
    time, so the name is more trustworthy -- mtime is only the fallback.
    """
    name = path.stem
    m = re.search(r"(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", name)
    if m:
        try:
            return datetime(*map(int, m.groups())).isoformat(timespec="seconds")
        except ValueError:
            pass
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", name)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return datetime(y, mo, d).isoformat(timespec="seconds")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def save_as_active(candidate: Calibration, data_dir: Path) -> Path | None:
    """Make `candidate` the calibration used from now on.

    The file it replaces is copied into calibrations/ first, so nothing is lost
    and any earlier calibration can be loaded back.
    Returns the backup path, if one was made.
    """
    data_dir = Path(data_dir)
    active = data_dir / CALIBRATION_FILE
    backup = None
    if active.exists():
        history = data_dir / HISTORY_DIR
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = history / f"replaced_{stamp}_{CALIBRATION_FILE}"
        shutil.copy2(active, backup)
    candidate.save(active)
    return backup


class _BaseWorker(threading.Thread):
    def __init__(self, rig: Rig, events: "queue.Queue"):
        super().__init__(daemon=True)
        self.rig = rig
        self.events = events
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def _should_stop(self) -> bool:
        return self._stop_evt.is_set()

    def emit(self, kind: str, payload=None) -> None:
        self.events.put((kind, payload))

    def log(self, message: str) -> None:
        self.emit("log", message)


class SetFieldWorker(_BaseWorker):
    """Ramp to a target field (in T) or a raw current (in A) and hold."""

    def __init__(self, rig, events, calibration: Calibration, target: float,
                 as_field: bool, compliance_v: float, ramp_step_a: float = 0.25,
                 ramp_delay_s: float = 0.1):
        super().__init__(rig, events)
        self.calibration = calibration
        self.target = target
        self.as_field = as_field
        self.compliance_v = compliance_v
        self.ramp_step_a = ramp_step_a
        self.ramp_delay_s = ramp_delay_s

    def run(self) -> None:
        try:
            if self.as_field:
                current = self.calibration.current_for_field(self.target)
                self.log(f"Target {self.target:+.4f} T -> {current:+.3f} A "
                         f"(using {self.calibration.slope:.6g} T/A)")
            else:
                current = self.target
                self.log(f"Target current {current:+.3f} A")

            self.rig.enable_supply(self.compliance_v)
            self.rig.ramp_current(current, self.ramp_step_a, self.ramp_delay_s,
                                  self._should_stop,
                                  on_step=lambda a: self.emit("field_step", a))
            if self._should_stop():
                self.log("Set-field cancelled; ramping down.")
                self.rig.safe_shutdown()
            else:
                time.sleep(1.0)
                self.log(f"Holding at {self.rig.read_field():+.4f} T "
                         f"({current:+.3f} A). Magnet stays energised.")
            self.emit("setfield_done", None)
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR: {exc}")
            self.rig.safe_shutdown()
            self.emit("error", str(exc))
        finally:
            self.emit("idle", None)


class RampDownWorker(_BaseWorker):
    """Bring the magnet to zero, optionally degaussing on the way."""

    def __init__(self, rig, events, degauss: bool = True,
                 start_a: float = 10.0, cycles: int = 8,
                 ramp_step_a: float = 0.25, ramp_delay_s: float = 0.05):
        super().__init__(rig, events)
        self.degauss = degauss
        self.start_a = start_a
        self.cycles = cycles
        self.ramp_step_a = ramp_step_a
        self.ramp_delay_s = ramp_delay_s

    def run(self) -> None:
        try:
            if self.degauss:
                self.log(f"Degaussing: {self.cycles} decaying cycles from "
                         f"{self.start_a:g} A.")
                amplitude = self.start_a
                sign = 1.0
                for i in range(self.cycles):
                    if self._should_stop():
                        break
                    self.rig.ramp_current(sign * amplitude, self.ramp_step_a,
                                          self.ramp_delay_s, self._should_stop)
                    self.emit("field_step", sign * amplitude)
                    self.log(f"  cycle {i + 1}/{self.cycles}: {sign * amplitude:+.2f} A")
                    amplitude *= 0.6
                    sign = -sign
            self.rig.ramp_current(0.0, self.ramp_step_a, self.ramp_delay_s,
                                  lambda: False)
            self.rig.safe_shutdown()
            self.log(f"Magnet off. Residual field {self.rig.read_field():+.5f} T.")
            self.emit("rampdown_done", None)
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR: {exc}")
            self.emit("error", str(exc))
        finally:
            self.emit("idle", None)


class CalibrationWorker(_BaseWorker):
    """Sweep current, log the gaussmeter, fit field = slope*I + intercept."""

    def __init__(self, rig, events, out_dir: Path, start_a: float, stop_a: float,
                 step_a: float, settle_s: float, compliance_v: float,
                 ramp_step_a: float = 0.25, ramp_delay_s: float = 0.1):
        super().__init__(rig, events)
        self.out_dir = Path(out_dir)
        self.start_a = start_a
        self.stop_a = stop_a
        self.step_a = abs(step_a)
        self.settle_s = settle_s
        self.compliance_v = compliance_v
        self.ramp_step_a = ramp_step_a
        self.ramp_delay_s = ramp_delay_s

    def run(self) -> None:
        try:
            n = int(round(abs(self.stop_a - self.start_a) / self.step_a)) + 1
            setpoints = np.linspace(self.start_a, self.stop_a, n)
            self.log(f"Calibrating over {self.start_a:+.2f} to {self.stop_a:+.2f} A "
                     f"in {n} steps.")

            self.rig.enable_supply(self.compliance_v)
            self.rig.ramp_current(float(setpoints[0]), self.ramp_step_a,
                                  self.ramp_delay_s, self._should_stop)

            applied, measured, fields = [], [], []
            for i, sp in enumerate(setpoints):
                if self._should_stop():
                    break
                self.rig.set_current(float(sp))
                time.sleep(self.settle_s)
                applied.append(float(sp))
                measured.append(self.rig.read_current())
                fields.append(self.rig.read_field())
                if i % 5 == 0:
                    self.emit("cal_progress", (i + 1, n))
                    self.emit("cal_points", (list(applied), list(fields)))

            if len(applied) < 3:
                raise RuntimeError("Not enough points to fit.")

            stamp = datetime.now()
            tag = stamp.strftime("%Y%m%d_%H%M%S")
            history = self.out_dir / HISTORY_DIR
            history.mkdir(parents=True, exist_ok=True)

            csv_path = history / f"calibration_{tag}.csv"
            # Header terminated with a newline -- the old writer omitted it and
            # glued the first data row onto the header.
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write("AppliedCurrent,MeasuredCurrent,field\n")
                for a, m, f in zip(applied, measured, fields):
                    fh.write(f"{a},{m},{f}\n")

            calibration = Calibration.from_points(
                applied, fields, source=str(csv_path),
                created=stamp.isoformat(timespec="seconds"),
                note="measured on the Calibration tab")

            png_path = history / f"calibration_{tag}.png"
            _plot_calibration(png_path, applied, fields, calibration.slope,
                              calibration.intercept, calibration.r_squared)
            calibration.save(history / f"calibration_{tag}.json")

            self.log(f"Fit: {calibration.slope:.6g} T/A, intercept "
                     f"{calibration.intercept:+.4g} T, R2={calibration.r_squared:.5f}")
            self.log(f"Saved to {HISTORY_DIR}/calibration_{tag}.* -- not active yet. "
                     f"Click 'Save as active' to use it.")
            self.emit("cal_done", calibration)

        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR: {exc}")
            self.emit("error", str(exc))
        finally:
            try:
                self.rig.safe_shutdown()
            except Exception:
                pass
            self.emit("idle", None)


def _plot_calibration(path: Path, currents, fields, slope, intercept, r2) -> None:
    fig = Figure(figsize=(6.5, 4.2), dpi=110)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.plot(currents, fields, "o", ms=3, color="#2f6fb2", label="measured")
    xs = np.linspace(min(currents), max(currents), 100)
    ax.plot(xs, slope * xs + intercept, "-", color="#c0392b",
            label=f"{slope:.5g} T/A  (R2={r2:.5f})")
    ax.set_xlabel("Applied current (A)")
    ax.set_ylabel("Measured field (T)")
    ax.set_title("Magnet calibration")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
