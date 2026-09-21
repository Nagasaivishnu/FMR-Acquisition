"""Frequency-swept FMR acquisition, run on a worker thread.

The worker never touches Tkinter. It pushes (event, payload) tuples onto a
queue and the UI drains that queue from the main thread.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .instruments import Rig
from .settings import Settings, write_metadata


def field_setpoints(start_a: float, stop_a: float, step_a: float) -> np.ndarray:
    """Inclusive, evenly spaced current setpoints.

    Built with linspace rather than `while curr <= stop: curr += step` so the
    endpoint is always hit exactly and the step never drifts by accumulated
    floating-point error over 1500 points.
    """
    span = abs(stop_a - start_a)
    n = int(round(span / abs(step_a))) + 1
    return np.linspace(start_a, stop_a, n)


def frequency_list(start_hz: float, stop_hz: float, step_hz: float) -> np.ndarray:
    n = int(round((stop_hz - start_hz) / step_hz))
    return start_hz + step_hz * np.arange(max(n, 1))


def unique_path(path: Path) -> Path:
    """Never silently overwrite an existing run."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_run{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many runs named like {path.name}")


def save_trace_png(path: Path, field_t, volx, voly, frequency_hz: float) -> None:
    """Quick-look plot for one frequency.

    Axis labels and the legend are applied *before* saving -- the old
    post_process called savefig first, so every auto-generated PNG in the
    archive is unlabelled.
    """
    field_t = np.asarray(field_t)
    r = np.hypot(np.asarray(volx), np.asarray(voly))

    fig = Figure(figsize=(7, 4.5), dpi=110)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.plot(field_t, r * 1e6, lw=1.1, color="#2f6fb2",
            label=f"{frequency_hz / 1e9:g} GHz")
    ax.set_xlabel("Magnetic field (T)")
    ax.set_ylabel("Lock-in R (uV)")
    ax.set_title(path.stem, fontsize=8)
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)


@dataclass
class SweepProgress:
    freq_index: int
    freq_total: int
    frequency_hz: float
    point_index: int
    point_total: int
    eta_s: float


class SweepWorker(threading.Thread):
    """Runs the full frequency x field sweep."""

    def __init__(self, settings: Settings, rig: Rig, events: "queue.Queue",
                 base_dir: Path):
        super().__init__(daemon=True)
        self.settings = settings
        self.rig = rig
        self.events = events
        self.base_dir = Path(base_dir)
        self._stop_evt = threading.Event()
        self._pause = threading.Event()
        self.written: list[Path] = []

    # ------------------------------------------------------------- controls

    def stop(self) -> None:
        self._stop_evt.set()
        self._pause.clear()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    def _should_stop(self) -> bool:
        return self._stop_evt.is_set()

    def _wait_if_paused(self) -> None:
        while self._pause.is_set() and not self._stop_evt.is_set():
            time.sleep(0.1)

    # ----------------------------------------------------------------- emit

    def emit(self, kind: str, payload=None) -> None:
        self.events.put((kind, payload))

    def log(self, message: str) -> None:
        self.emit("log", message)

    # ------------------------------------------------------------------ run

    def run(self) -> None:
        st = self.settings
        sw = st.sweep
        out_dir = self.base_dir / st.output_folder
        out_dir.mkdir(parents=True, exist_ok=True)

        frequencies = frequency_list(sw.start_frequency_hz, sw.stop_frequency_hz,
                                     sw.frequency_step_hz)
        setpoints = field_setpoints(sw.current_start_a, sw.current_stop_a,
                                    sw.current_step_a)
        started = datetime.now()

        try:
            self.log(f"Output folder: {out_dir}")
            self.log(f"{len(frequencies)} frequencies x {len(setpoints)} field points")

            applied = self.rig.configure_lockin(st.lockin)
            if applied.sensitivity_v != st.lockin.sensitivity_v:
                self.log(f"Sensitivity snapped to {applied.sensitivity_tag} "
                         f"(nearest SR830 step).")
            st.lockin = applied
            self.emit("lockin_applied", applied)

            self.rig.enable_supply(st.instruments.supply_compliance_v)
            self.log(f"Ramping magnet to start ({sw.current_start_a:+.2f} A)...")
            self.rig.ramp_current(sw.current_start_a, sw.ramp_step_a,
                                  sw.ramp_delay_s, self._should_stop)
            if self._should_stop():
                raise Aborted()

            meta_path = out_dir / f"{st.file_prefix()}_run_metadata.json"
            write_metadata(unique_path(meta_path), st, {
                "started": started.isoformat(timespec="seconds"),
                "frequencies_hz": [float(f) for f in frequencies],
                "field_setpoints_a": [float(setpoints[0]), float(setpoints[-1])],
                "n_field_points": int(len(setpoints)),
                "instrument_ids": self.rig.identities,
            })

            point_seconds = sw.settle_s + 0.05
            total_points = len(frequencies) * len(setpoints)
            done_points = 0

            for f_index, frequency in enumerate(frequencies):
                self._wait_if_paused()
                if self._should_stop():
                    raise Aborted()

                self.rig.set_microwave(float(frequency), sw.power_dbm)
                self.rig.rf_output(True)
                self.emit("freq_start", (f_index, len(frequencies), float(frequency)))

                # Return to the start of the field ramp between frequencies.
                self.rig.ramp_current(float(setpoints[0]), sw.ramp_step_a,
                                      sw.ramp_delay_s, self._should_stop)
                time.sleep(max(sw.settle_s, st.lockin.time_constant_s * 3))

                currents, fields, volx, voly = [], [], [], []

                for p_index, setpoint in enumerate(setpoints):
                    self._wait_if_paused()
                    if self._should_stop():
                        raise Aborted()

                    self.rig.set_current(float(setpoint))
                    time.sleep(sw.settle_s)

                    x, y = self.rig.read_xy()
                    field = self.rig.read_field()

                    # Log the setpoint that was actually applied for this
                    # reading. The old loop advanced `curr` before appending,
                    # so every recorded Current was one step ahead of the
                    # measurement.
                    currents.append(float(setpoint))
                    fields.append(field)
                    volx.append(x)
                    voly.append(y)

                    done_points += 1
                    if p_index % 5 == 0 or p_index == len(setpoints) - 1:
                        remaining = (total_points - done_points) * point_seconds
                        self.emit("progress", SweepProgress(
                            f_index, len(frequencies), float(frequency),
                            p_index + 1, len(setpoints), remaining))
                        self.emit("trace", (float(frequency),
                                            list(fields), list(volx), list(voly)))

                csv_path = unique_path(out_dir / st.csv_name(float(frequency)))
                _write_csv(csv_path, currents, fields, volx, voly)
                save_trace_png(csv_path.with_suffix(".png"), fields, volx, voly,
                               float(frequency))
                self.written.append(csv_path)
                self.log(f"Saved {csv_path.name}")
                self.emit("freq_done", csv_path)

            self.emit("finished", len(self.written))

        except Aborted:
            self.log("Sweep stopped by user.")
            self.emit("aborted", len(self.written))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI log
            self.log(f"ERROR: {exc}")
            self.emit("error", str(exc))
        finally:
            # Whatever happened, bring the magnet and RF down. The old script
            # left the supply energised on any exception or Ctrl-C.
            self.log("Ramping magnet down and disabling output...")
            try:
                self.rig.safe_shutdown()
            except Exception as exc:  # noqa: BLE001
                self.log(f"Shutdown warning: {exc}")
            self.emit("idle", None)


class Aborted(Exception):
    pass


def _write_csv(path: Path, currents, fields, volx, voly) -> None:
    """Exactly the legacy four-column format -- no comment header -- so the
    existing analysis scripts keep working on these files unmodified."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("Current,field,voltageX,voltageY\n")
        for c, f, x, y in zip(currents, fields, volx, voly):
            fh.write(f"{round(c, 4)},{f},{x},{y}\n")
