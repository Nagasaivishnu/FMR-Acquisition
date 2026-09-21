"""Magnet utilities: set-field, degauss, ramp-down and current-to-field
calibration.

Replaces the old `set_field.py` and the extensionless `calibrate_power_supply`
script, with the coefficients stored in a file instead of pasted into the
source as a literal.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .instruments import Rig

CALIBRATION_FILE = "magnet_calibration.json"


@dataclass
class Calibration:
    """field_T = slope * current_A + intercept."""

    slope: float = 0.0267
    intercept: float = 0.0
    r_squared: float = 0.0
    n_points: int = 0
    current_range_a: tuple = (0.0, 0.0)
    created: str = ""
    note: str = "default estimate -- run a calibration to replace"

    def current_for_field(self, field_t: float) -> float:
        if self.slope == 0:
            raise ValueError("Calibration slope is zero.")
        return (field_t - self.intercept) / self.slope

    def field_for_current(self, current_a: float) -> float:
        return self.slope * current_a + self.intercept

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        if not Path(path).exists():
            return cls()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["current_range_a"] = tuple(data.get("current_range_a", (0.0, 0.0)))
        return cls(**data)

    def describe(self) -> str:
        if not self.created:
            return f"{self.slope:.6g} T/A (default, not measured)"
        return (f"{self.slope:.6g} T/A, offset {self.intercept:+.4g} T "
                f"| R2={self.r_squared:.5f} | {self.n_points} pts "
                f"| {self.created[:10]}")


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

            slope, intercept = np.polyfit(applied, fields, 1)
            predicted = np.polyval([slope, intercept], applied)
            ss_res = float(np.sum((np.array(fields) - predicted) ** 2))
            ss_tot = float(np.sum((np.array(fields) - np.mean(fields)) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

            stamp = datetime.now()
            calibration = Calibration(
                slope=float(slope), intercept=float(intercept), r_squared=r2,
                n_points=len(applied),
                current_range_a=(float(applied[0]), float(applied[-1])),
                created=stamp.isoformat(timespec="seconds"),
                note="measured with CalibrationWorker",
            )

            self.out_dir.mkdir(parents=True, exist_ok=True)
            tag = stamp.strftime("%Y%m%d_%H%M%S")

            csv_path = self.out_dir / f"calibration_{tag}.csv"
            # Header terminated with a newline -- the old writer omitted it and
            # glued the first data row onto the header.
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write("AppliedCurrent,MeasuredCurrent,field\n")
                for a, m, f in zip(applied, measured, fields):
                    fh.write(f"{a},{m},{f}\n")

            png_path = self.out_dir / f"calibration_{tag}.png"
            _plot_calibration(png_path, applied, fields, slope, intercept, r2)

            calibration.save(self.out_dir / CALIBRATION_FILE)
            self.log(f"Fit: {slope:.6g} T/A, intercept {intercept:+.4g} T, R2={r2:.5f}")
            self.log(f"Saved {csv_path.name}, {png_path.name} and {CALIBRATION_FILE}")
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
