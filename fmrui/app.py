"""Tkinter front end for the FMR acquisition rig."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .acquisition import SweepWorker, field_setpoints, frequency_list
from .fieldtools import (
    CALIBRATION_FILE,
    HISTORY_DIR,
    Calibration,
    CalibrationWorker,
    RampDownWorker,
    SetFieldWorker,
    save_as_active,
)
from .instruments import make_rig
from .paths import save_data_dir
from .settings import (
    FILTER_SLOPES,
    SENSITIVITIES,
    TIME_CONSTANTS,
    Settings,
    format_sensitivity,
)

BG = "#f5f6f8"
ACCENT = "#2f6fb2"
STOP_RED = "#c0392b"
MONO = ("Consolas", 9)


class FMRApp(tk.Tk):
    def __init__(self, base_dir: Path, source: str = "default"):
        super().__init__()
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data_source = source
        self.title("FMR Acquisition")
        self.geometry("1200x860")
        self.minsize(1000, 660)
        self.configure(bg=BG)

        self.settings = Settings()
        self.calibration = Calibration.load(self.base_dir / CALIBRATION_FILE)
        self.cal_candidate = None   # a run or loaded file awaiting Save/Discard
        self.rig = None
        self.worker = None
        self.events: "queue.Queue" = queue.Queue()
        self._monitor_stop = threading.Event()
        self._monitor = None

        self._build_style()
        self._build_layout()
        self._load_settings_into_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_id = self.after(100, self._drain_events)
        self.log(f"Data folder: {self.base_dir}  ({self.data_source})")
        if self.data_source == "default":
            self.log("Tip: Sweep tab -> 'Change...' to point at your FMR data folder.")
        self._log_active_calibration()

    # ------------------------------------------------------------ appearance

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=BG, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=BG,
                        foreground="#444", font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background=BG)
        style.configure("Hint.TLabel", foreground="#777", font=("Segoe UI", 9))
        style.configure("Head.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Stat.TLabel", font=("Consolas", 11))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8))
        style.configure("Accent.TButton", foreground="white", background=ACCENT,
                        padding=(14, 7), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#245a92"),
                                                ("disabled", "#a9c2da")])
        style.configure("Stop.TButton", foreground="white", background=STOP_RED,
                        padding=(14, 7), font=("Segoe UI", 10, "bold"))
        style.map("Stop.TButton", background=[("active", "#96301f"),
                                              ("disabled", "#e0b3ac")])
        style.configure("TButton", padding=(10, 6))

    def _build_layout(self) -> None:
        header = ttk.Frame(self, padding=(14, 10, 14, 6))
        header.pack(fill="x")
        ttk.Label(header, text="FMR Acquisition", style="Head.TLabel").pack(side="left")

        self.var_status = tk.StringVar(value="Not connected")
        self.var_field = tk.StringVar(value="field  ---")
        ttk.Label(header, textvariable=self.var_field,
                  style="Stat.TLabel").pack(side="right", padx=(16, 0))
        ttk.Label(header, textvariable=self.var_status,
                  style="Stat.TLabel").pack(side="right")

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.nb = ttk.Notebook(paned)
        paned.add(self.nb, weight=4)

        self.tab_sweep = ttk.Frame(self.nb, padding=12)
        self.tab_field = ttk.Frame(self.nb, padding=12)
        self.tab_cal = ttk.Frame(self.nb, padding=12)
        self.tab_conn = ttk.Frame(self.nb, padding=12)
        self.nb.add(self.tab_sweep, text="Sweep")
        self.nb.add(self.tab_field, text="Field")
        self.nb.add(self.tab_cal, text="Calibration")
        self.nb.add(self.tab_conn, text="Instruments")

        log_frame = ttk.Labelframe(paned, text="Log", padding=6)
        paned.add(log_frame, weight=1)
        self.log_box = tk.Text(log_frame, height=8, font=MONO, wrap="none",
                               bg="#ffffff", relief="flat", borderwidth=1)
        scroll = ttk.Scrollbar(log_frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set, state="disabled")
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._build_conn_tab()
        self._build_sweep_tab()
        self._build_field_tab()
        self._build_cal_tab()

    # -------------------------------------------------------------- helpers

    def _scroll_column(self, parent, width=372):
        """Fixed-width, vertically scrollable column.

        Keeps every field reachable on a short laptop screen instead of
        letting the form run off the bottom of the window.
        """
        holder = ttk.Frame(parent, width=width)
        holder.pack_propagate(False)
        canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, width=width - 16)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        def on_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"),
                        add="+")
        return holder, inner

    def _row(self, parent, row, label, var, width=14, hint=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           pady=3, padx=(0, 8))
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="w", pady=3)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row, column=2, sticky="w", padx=(8, 0))
        return entry

    def _combo(self, parent, row, label, var, values, hint=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           pady=3, padx=(0, 8))
        box = ttk.Combobox(parent, textvariable=var, values=values, width=12,
                           state="readonly")
        box.grid(row=row, column=1, sticky="w", pady=3)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row, column=2, sticky="w", padx=(8, 0))
        return box

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------ instruments tab

    def _build_conn_tab(self) -> None:
        t = self.tab_conn
        box = ttk.Labelframe(t, text="Addresses", padding=12)
        box.pack(fill="x")

        self.v_pna = tk.StringVar()
        self.v_lockin = tk.StringVar()
        self.v_supply = tk.StringVar()
        self.v_gauss = tk.StringVar()
        self.v_compliance = tk.StringVar()
        self.v_simulate = tk.BooleanVar(value=False)

        self._row(box, 0, "PNA (microwave source)", self.v_pna, 24)
        self._row(box, 1, "SR830 lock-in", self.v_lockin, 24)
        self._row(box, 2, "Kepco supply", self.v_supply, 24)
        self._row(box, 3, "LakeShore gaussmeter", self.v_gauss, 24,
                  "one place for the port -- used by every tab")
        self._row(box, 4, "Supply compliance (V)", self.v_compliance, 10)

        ttk.Checkbutton(box, text="Simulate (no hardware -- synthetic resonance)",
                        variable=self.v_simulate).grid(row=5, column=0, columnspan=3,
                                                       sticky="w", pady=(10, 0))

        buttons = ttk.Frame(t, padding=(0, 12))
        buttons.pack(fill="x")
        self.btn_connect = ttk.Button(buttons, text="Connect", style="Accent.TButton",
                                      command=self.on_connect)
        self.btn_connect.pack(side="left")
        self.btn_disconnect = ttk.Button(buttons, text="Disconnect",
                                         command=self.on_disconnect, state="disabled")
        self.btn_disconnect.pack(side="left", padx=8)

        idbox = ttk.Labelframe(t, text="Identification", padding=10)
        idbox.pack(fill="both", expand=True)
        self.id_box = tk.Text(idbox, height=8, font=MONO, wrap="word",
                              bg="#ffffff", relief="flat", borderwidth=1)
        self.id_box.pack(fill="both", expand=True)
        self.id_box.configure(state="disabled")

    # ------------------------------------------------------------ sweep tab

    def _build_sweep_tab(self) -> None:
        t = self.tab_sweep
        column = ttk.Frame(t)
        column.pack(side="left", fill="y", padx=(0, 14))
        holder, left = self._scroll_column(column)
        holder.pack(side="top", fill="both", expand=True)
        footer = ttk.Frame(column, padding=(0, 8, 0, 0))
        footer.pack(side="bottom", fill="x")
        right = ttk.Frame(t)
        right.pack(side="left", fill="both", expand=True)

        run = ttk.Labelframe(left, text="Run", padding=10)
        run.pack(fill="x")
        self.v_sample = tk.StringVar()
        self.v_outdir = tk.StringVar()
        self._row(run, 0, "Sample identity", self.v_sample, 18)
        self._row(run, 1, "Output folder", self.v_outdir, 18)

        ttk.Label(run, text="Data folder").grid(row=2, column=0, sticky="w",
                                                pady=3, padx=(0, 8))
        ttk.Button(run, text="Change...", command=self.on_change_data_dir).grid(
            row=2, column=1, sticky="w", pady=3)
        self.v_datadir = tk.StringVar(value=str(self.base_dir))
        ttk.Label(run, textvariable=self.v_datadir, style="Hint.TLabel",
                  wraplength=320, justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w")

        self.v_prefix = tk.StringVar(value="")
        ttk.Label(run, textvariable=self.v_prefix, style="Hint.TLabel",
                  wraplength=320, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        mw = ttk.Labelframe(left, text="Microwave", padding=10)
        mw.pack(fill="x", pady=(10, 0))
        self.v_fstart = tk.StringVar()
        self.v_fstop = tk.StringVar()
        self.v_fstep = tk.StringVar()
        self.v_power = tk.StringVar()
        self._row(mw, 0, "Start (GHz)", self.v_fstart)
        self._row(mw, 1, "Stop (GHz)", self.v_fstop, hint="exclusive")
        self._row(mw, 2, "Step (MHz)", self.v_fstep)
        self._row(mw, 3, "Power (dBm)", self.v_power)

        mag = ttk.Labelframe(left, text="Field sweep", padding=10)
        mag.pack(fill="x", pady=(10, 0))
        self.v_istart = tk.StringVar()
        self.v_istop = tk.StringVar()
        self.v_istep = tk.StringVar()
        self.v_settle = tk.StringVar()
        self._row(mag, 0, "Start (A)", self.v_istart, hint="start > stop = reverse")
        self._row(mag, 1, "Stop (A)", self.v_istop)
        self._row(mag, 2, "Step (A)", self.v_istep)
        self._row(mag, 3, "Settle (s)", self.v_settle, hint=">= time constant")

        lk = ttk.Labelframe(left, text="Lock-in", padding=10)
        lk.pack(fill="x", pady=(10, 0))
        self.v_amp = tk.StringVar()
        self.v_ref = tk.StringVar()
        self.v_phase = tk.StringVar()
        self.v_slope = tk.StringVar()
        self.v_tc = tk.StringVar()
        self.v_sens = tk.StringVar()
        self._row(lk, 0, "Amplitude (V)", self.v_amp)
        self._row(lk, 1, "Reference (Hz)", self.v_ref)
        self._row(lk, 2, "Phase (deg)", self.v_phase)
        self._combo(lk, 3, "Filter slope", self.v_slope,
                    [str(s) for s in FILTER_SLOPES], "dB/oct")
        self._combo(lk, 4, "Time constant", self.v_tc,
                    [f"{v:g}" for v in TIME_CONSTANTS], "s")
        self._combo(lk, 5, "Sensitivity", self.v_sens,
                    [format_sensitivity(v) for v in SENSITIVITIES],
                    "applied + named")
        self.v_sens.trace_add("write", lambda *_: self._refresh_preview())
        self.v_sample.trace_add("write", lambda *_: self._refresh_preview())

        cfg = ttk.Frame(left, padding=(0, 10, 0, 0))
        cfg.pack(fill="x")
        ttk.Button(cfg, text="Load config...", command=self.on_load_config).pack(
            side="left")
        ttk.Button(cfg, text="Save config...", command=self.on_save_config).pack(
            side="left", padx=6)

        # Run controls sit outside the scroll area so they are always visible.
        self.btn_start = ttk.Button(footer, text="Start sweep", style="Accent.TButton",
                                    command=self.on_start_sweep)
        self.btn_start.pack(side="left")
        self.btn_pause = ttk.Button(footer, text="Pause", command=self.on_pause,
                                    state="disabled")
        self.btn_pause.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(footer, text="Stop", style="Stop.TButton",
                                   command=self.on_stop_sweep, state="disabled")
        self.btn_stop.pack(side="left")

        # ---- right: run summary, plot, progress
        self.v_plan = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.v_plan, style="Hint.TLabel",
                  wraplength=680, justify="left").pack(anchor="w", pady=(0, 6))

        self.fig = Figure(figsize=(5.6, 3.9), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self._reset_plot()
        # Progress is packed to the bottom first so the bar is never pushed
        # off-screen by the plot.
        prog = ttk.Frame(right, padding=(0, 8, 0, 0))
        prog.pack(side="bottom", fill="x")
        self.v_prog_text = tk.StringVar(value="Idle")
        ttk.Label(prog, textvariable=self.v_prog_text, style="Stat.TLabel").pack(
            anchor="w")
        self.pbar = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.pbar.pack(fill="x", pady=(5, 0))

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

        for var in (self.v_fstart, self.v_fstop, self.v_fstep, self.v_istart,
                    self.v_istop, self.v_istep, self.v_settle):
            var.trace_add("write", lambda *_: self._refresh_preview())

    def _reset_plot(self) -> None:
        self.ax.clear()
        self.ax.set_xlabel("Magnetic field (T)")
        self.ax.set_ylabel("Lock-in R (uV)")
        self.ax.grid(alpha=0.3)
        self.ax.set_title("Live trace")

    # ------------------------------------------------------------ field tab

    def _build_field_tab(self) -> None:
        t = self.tab_field
        box = ttk.Labelframe(t, text="Set field", padding=12)
        box.pack(fill="x")
        self.v_target = tk.StringVar(value="0.05")
        self.v_target_unit = tk.StringVar(value="T")
        self._row(box, 0, "Target", self.v_target, 12)
        ttk.Radiobutton(box, text="tesla", variable=self.v_target_unit,
                        value="T").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Radiobutton(box, text="amps", variable=self.v_target_unit,
                        value="A").grid(row=0, column=3, sticky="w")

        self.v_cal_text = tk.StringVar()
        ttk.Label(box, textvariable=self.v_cal_text, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        btns = ttk.Frame(t, padding=(0, 12))
        btns.pack(fill="x")
        self.btn_setfield = ttk.Button(btns, text="Go to field",
                                       style="Accent.TButton",
                                       command=self.on_set_field)
        self.btn_setfield.pack(side="left")
        ttk.Button(btns, text="Ramp down", command=lambda: self.on_ramp_down(False)
                   ).pack(side="left", padx=8)
        ttk.Button(btns, text="Degauss + ramp down",
                   command=lambda: self.on_ramp_down(True)).pack(side="left")
        self.btn_estop = ttk.Button(btns, text="STOP / magnet off", style="Stop.TButton",
                                    command=self.on_emergency_stop)
        self.btn_estop.pack(side="right")

        note = ttk.Labelframe(t, text="Notes", padding=12)
        note.pack(fill="both", expand=True)
        ttk.Label(note, style="Hint.TLabel", justify="left", text=(
            "• 'Go to field' converts tesla to amps with the ACTIVE calibration\n"
            "  (Calibration tab) and leaves the magnet energised so you can\n"
            "  mount or measure a sample.\n"
            "• 'Degauss + ramp down' walks a decaying alternating current to zero,\n"
            "  which clears remanence before you remove the sample.\n"
            "• 'STOP / magnet off' aborts whatever is running and ramps to zero.\n"
            "• Every worker ramps the supply down in a finally block, so an error\n"
            "  or a closed window cannot leave the magnet energised."
        )).pack(anchor="w")

    # ------------------------------------------------------ calibration tab

    def _build_cal_tab(self) -> None:
        t = self.tab_cal
        column = ttk.Frame(t)
        column.pack(side="left", fill="y", padx=(0, 14))
        # Save / Discard are pinned below the scroll area so the decision is
        # always on screen, whatever the window height.
        footer = ttk.Frame(column, padding=(0, 8, 0, 0))
        footer.pack(side="bottom", fill="x")
        holder, left = self._scroll_column(column, width=352)
        holder.pack(side="top", fill="both", expand=True)
        right = ttk.Frame(t)
        right.pack(side="left", fill="both", expand=True)

        # ---- 1. what is in use now
        cur = ttk.Labelframe(left, text="Active calibration  (used by the Field tab)",
                             padding=10)
        cur.pack(fill="x")
        self.v_cal_detail = tk.StringVar()
        ttk.Label(cur, textvariable=self.v_cal_detail, font=MONO, background=BG,
                  justify="left").pack(anchor="w")
        self.v_cal_status = tk.StringVar()
        ttk.Label(cur, textvariable=self.v_cal_status, style="Hint.TLabel",
                  wraplength=300, justify="left").pack(anchor="w", pady=(6, 0))

        # ---- 2. the candidate awaiting a decision
        self.cand_box = ttk.Labelframe(left, text="New result  (not in use yet)",
                                       padding=10)
        self.cand_box.pack(fill="x", pady=(10, 0))
        self.v_cand_detail = tk.StringVar()
        ttk.Label(self.cand_box, textvariable=self.v_cand_detail, font=MONO,
                  background=BG, justify="left", wraplength=320).pack(anchor="w")

        # ---- 3. where a new one comes from
        box = ttk.Labelframe(left, text="Get a new calibration", padding=10)
        box.pack(fill="x", pady=(10, 0))
        self.v_cal_start = tk.StringVar(value="-10")
        self.v_cal_stop = tk.StringVar(value="10")
        self.v_cal_step = tk.StringVar(value="0.2")
        self.v_cal_settle = tk.StringVar(value="0.5")
        self._row(box, 0, "Start (A)", self.v_cal_start, 10)
        self._row(box, 1, "Stop (A)", self.v_cal_stop, 10)
        self._row(box, 2, "Step (A)", self.v_cal_step, 10)
        self._row(box, 3, "Settle (s)", self.v_cal_settle, 10)
        btns = ttk.Frame(box, padding=(0, 8, 0, 0))
        btns.grid(row=4, column=0, columnspan=3, sticky="w")
        self.btn_cal = ttk.Button(btns, text="Run calibration", command=self.on_calibrate)
        self.btn_cal.pack(side="left")
        ttk.Button(btns, text="Load from file...", command=self.on_load_cal).pack(
            side="left", padx=6)
        ttk.Label(box, style="Hint.TLabel", wraplength=300, justify="left", text=(
            "Load accepts a calibration .json (from calibrations/) or a .csv of "
            "current and field -- including the old calibrated_data_*.csv files. "
            "Every run is archived in calibrations/ whether or not you save it."
        )).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(box, text="Open calibrations folder",
                   command=self.on_open_cal_folder).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.btn_cand_save = ttk.Button(footer, text="Save as active",
                                        style="Accent.TButton", state="disabled",
                                        command=self.on_save_candidate)
        self.btn_cand_save.pack(side="left")
        self.btn_cand_discard = ttk.Button(footer, text="Discard", state="disabled",
                                           command=self.on_discard_candidate)
        self.btn_cand_discard.pack(side="left", padx=6)

        # ---- plot
        self.cal_fig = Figure(figsize=(5.8, 4.2), dpi=100)
        self.cal_ax = self.cal_fig.add_subplot(111)
        self.cal_canvas = FigureCanvasTkAgg(self.cal_fig, master=right)
        self.cal_canvas.get_tk_widget().pack(fill="both", expand=True)

        self._refresh_calibration_labels()

    def _draw_calibration_plot(self, live_points=None) -> None:
        """Active calibration as a grey reference; candidate (or a live run)
        on top, so the difference is visible before you commit to it."""
        ax = self.cal_ax
        ax.clear()
        active, cand = self.calibration, self.cal_candidate

        spans = [c.current_range_a for c in (active, cand)
                 if c is not None and c.is_measured]
        if live_points and live_points[0]:
            spans.append((min(live_points[0]), max(live_points[0])))
        lo = min((s_[0] for s_ in spans), default=-10.0)
        hi = max((s_[1] for s_ in spans), default=10.0)
        if lo == hi:
            lo, hi = lo - 1, hi + 1
        xs = np.linspace(lo, hi, 50)

        label = "active" if active.is_measured else "active (default estimate)"
        ax.plot(xs, active.field_for_current(xs), "--", color="#888", lw=1.5,
                label=f"{label}: {active.slope:.5g} T/A")

        if cand is not None:
            if cand.currents and len(cand.currents) > 2:
                step = max(1, len(cand.currents) // 400)
                ax.plot(cand.currents[::step], cand.fields[::step], "o", ms=2.5,
                        color=ACCENT, alpha=0.7, label="new: measured")
            ax.plot(xs, cand.field_for_current(xs), "-", color=STOP_RED, lw=1.6,
                    label=f"new fit: {cand.slope:.5g} T/A (R2={cand.r_squared:.5f})")
        if live_points:
            ax.plot(live_points[0], live_points[1], "o", ms=3, color=ACCENT,
                    label="measuring...")

        ax.set_xlabel("Applied current (A)")
        ax.set_ylabel("Field (T)")
        ax.set_title("Magnet calibration")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", fontsize=8)
        self.cal_canvas.draw_idle()

    # ------------------------------------------------------------- settings

    def _load_settings_into_widgets(self) -> None:
        s, sw, lk, ins = (self.settings, self.settings.sweep,
                          self.settings.lockin, self.settings.instruments)
        self.v_pna.set(ins.pna_address)
        self.v_lockin.set(ins.lockin_address)
        self.v_supply.set(ins.supply_address)
        self.v_gauss.set(ins.gaussmeter_address)
        self.v_compliance.set(f"{ins.supply_compliance_v:g}")
        self.v_simulate.set(ins.simulate)

        self.v_sample.set(s.sample_identity)
        self.v_outdir.set(s.output_folder)
        self.v_fstart.set(f"{sw.start_frequency_hz / 1e9:g}")
        self.v_fstop.set(f"{sw.stop_frequency_hz / 1e9:g}")
        self.v_fstep.set(f"{sw.frequency_step_hz / 1e6:g}")
        self.v_power.set(f"{sw.power_dbm:g}")
        self.v_istart.set(f"{sw.current_start_a:g}")
        self.v_istop.set(f"{sw.current_stop_a:g}")
        self.v_istep.set(f"{sw.current_step_a:g}")
        self.v_settle.set(f"{sw.settle_s:g}")
        self.v_amp.set(f"{lk.amplitude_v:g}")
        self.v_ref.set(f"{lk.reference_hz:g}")
        self.v_phase.set(f"{lk.phase_deg:g}")
        self.v_slope.set(str(lk.filter_slope_db))
        self.v_tc.set(f"{lk.time_constant_s:g}")
        self.v_sens.set(format_sensitivity(lk.sensitivity_v))
        self._refresh_preview()

    def _collect_settings(self) -> Settings:
        s = self.settings
        f = _to_float
        s.sample_identity = self.v_sample.get().strip()
        s.output_folder = self.v_outdir.get().strip() or "run_output"

        ins = s.instruments
        ins.pna_address = self.v_pna.get().strip()
        ins.lockin_address = self.v_lockin.get().strip()
        ins.supply_address = self.v_supply.get().strip()
        ins.gaussmeter_address = self.v_gauss.get().strip()
        ins.supply_compliance_v = f(self.v_compliance.get(), 14.0)
        ins.simulate = bool(self.v_simulate.get())

        sw = s.sweep
        sw.start_frequency_hz = f(self.v_fstart.get(), 2.0) * 1e9
        sw.stop_frequency_hz = f(self.v_fstop.get(), 20.0) * 1e9
        sw.frequency_step_hz = f(self.v_fstep.get(), 50.0) * 1e6
        sw.power_dbm = f(self.v_power.get(), 0.0)
        sw.current_start_a = f(self.v_istart.get(), 15.0)
        sw.current_stop_a = f(self.v_istop.get(), -15.0)
        sw.current_step_a = abs(f(self.v_istep.get(), 0.02))
        sw.settle_s = f(self.v_settle.get(), 0.3)

        lk = s.lockin
        lk.amplitude_v = f(self.v_amp.get(), 4.0)
        lk.reference_hz = f(self.v_ref.get(), 113.52)
        lk.phase_deg = f(self.v_phase.get(), 0.0)
        lk.filter_slope_db = int(f(self.v_slope.get(), 24))
        lk.time_constant_s = f(self.v_tc.get(), 0.3)
        lk.sensitivity_v = _sensitivity_from_tag(self.v_sens.get())
        return s

    def _refresh_preview(self, *_):
        try:
            s = self._collect_settings()
            freqs = frequency_list(s.sweep.start_frequency_hz,
                                   s.sweep.stop_frequency_hz,
                                   s.sweep.frequency_step_hz)
            points = field_setpoints(s.sweep.current_start_a, s.sweep.current_stop_a,
                                     s.sweep.current_step_a)
            seconds = len(freqs) * len(points) * (s.sweep.settle_s + 0.05)
            self.v_plan.set(
                f"{len(freqs)} frequencies x {len(points)} points  |  "
                f"~{seconds / 3600:.1f} h  |  "
                f"{len(freqs)} CSV + {len(freqs)} PNG + 1 metadata JSON")
            self.v_prefix.set(f"files: {s.csv_name(s.sweep.start_frequency_hz)}")
        except Exception:
            self.v_plan.set("")

    def _refresh_calibration_labels(self) -> None:
        c = self.calibration
        self.v_cal_text.set(f"Calibration: {c.describe()}")
        self.v_cal_detail.set(_cal_block(c))
        active_file = self.base_dir / CALIBRATION_FILE
        if c.is_measured:
            self.v_cal_status.set(f"From {active_file.name} in the data folder; "
                                  f"loaded automatically at every start.")
        else:
            self.v_cal_status.set(f"No {CALIBRATION_FILE} in the data folder -- using "
                                  f"a rough default. Run or load a calibration, "
                                  f"then 'Save as active'.")

        cand = self.cal_candidate
        if cand is None:
            self.v_cand_detail.set("None. Run a calibration or load a file below;\n"
                                   "the active one stays in use until you\n"
                                   "click 'Save as active'.")
            state = "disabled"
        else:
            self.v_cand_detail.set(_cal_block(cand) + "\n\n" + cand.compare(c))
            state = "normal"
        self.btn_cand_save.configure(state=state)
        self.btn_cand_discard.configure(state=state)
        self._draw_calibration_plot()

    def _log_active_calibration(self) -> None:
        c = self.calibration
        if c.is_measured:
            self.log(f"Calibration in use: {c.describe()}  "
                     f"[{self.base_dir / CALIBRATION_FILE}]")
        else:
            self.log(f"WARNING: no {CALIBRATION_FILE} in the data folder -- field "
                     f"targets use a default {c.slope:g} T/A estimate.")

    # ------------------------------------------------------------- commands

    def on_load_config(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(self.base_dir), title="Load config",
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.settings = Settings.load(path)
            self._load_settings_into_widgets()
            self.log(f"Loaded config {Path(path).name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Load failed", str(exc))

    def on_save_config(self) -> None:
        path = filedialog.asksaveasfilename(
            initialdir=str(self.base_dir), title="Save config",
            defaultextension=".yaml", initialfile="fmr_config.yaml",
            filetypes=[("YAML", "*.yaml")])
        if not path:
            return
        self._collect_settings().save(path)
        self.log(f"Saved config {Path(path).name}")

    def on_connect(self) -> None:
        s = self._collect_settings()
        try:
            self.rig = make_rig(s.instruments)
            ids = self.rig.connect()
        except Exception as exc:  # noqa: BLE001
            self.rig = None
            messagebox.showerror("Connection failed", str(exc))
            self.log(f"Connect failed: {exc}")
            return
        self.id_box.configure(state="normal")
        self.id_box.delete("1.0", "end")
        for name, ident in ids.items():
            self.id_box.insert("end", f"{name:<12} {ident}\n")
        self.id_box.configure(state="disabled")
        mode = "SIMULATED" if s.instruments.simulate else "Connected"
        self.var_status.set(mode)
        self.btn_connect.configure(state="disabled")
        self.btn_disconnect.configure(state="normal")
        self.log(f"{mode}: {len(ids)} instruments.")
        self._start_monitor()

    def on_disconnect(self) -> None:
        self._stop_monitor()
        if self.rig is not None:
            self.rig.close()
            self.rig = None
        self.var_status.set("Not connected")
        self.var_field.set("field  ---")
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.log("Disconnected; magnet ramped down.")

    def _require_rig(self) -> bool:
        if self.rig is None:
            messagebox.showwarning("Not connected",
                                   "Connect on the Instruments tab first.")
            return False
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("Busy", "Another operation is still running.")
            return False
        return True

    def on_start_sweep(self) -> None:
        if not self._require_rig():
            return
        s = self._collect_settings()
        problems = s.validate()
        if problems:
            if not messagebox.askyesno(
                    "Check settings",
                    "\n".join(f"• {p}" for p in problems) + "\n\nStart anyway?"):
                return

        out_dir = self.base_dir / s.output_folder
        if out_dir.exists() and any(out_dir.glob("*FMR*.csv")):
            if not messagebox.askyesno(
                    "Folder in use",
                    f"{out_dir.name} already contains FMR CSVs.\n"
                    "New files with clashing names get a _run2 suffix "
                    "rather than overwriting.\n\nContinue?"):
                return

        self._stop_monitor()
        self._reset_plot()
        self.canvas.draw_idle()
        self.worker = SweepWorker(s, self.rig, self.events, self.base_dir)
        self.worker.start()
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="Pause")
        self.btn_stop.configure(state="normal")
        self.var_status.set("Sweeping")
        self.log("Sweep started.")

    def on_pause(self) -> None:
        if not isinstance(self.worker, SweepWorker):
            return
        if self.worker.paused:
            self.worker.resume()
            self.btn_pause.configure(text="Pause")
            self.log("Resumed.")
        else:
            self.worker.pause()
            self.btn_pause.configure(text="Resume")
            self.log("Paused (magnet holds at the current setpoint).")

    def on_stop_sweep(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.log("Stop requested; finishing the current point.")

    def on_set_field(self) -> None:
        if not self._require_rig():
            return
        s = self._collect_settings()
        target = _to_float(self.v_target.get(), 0.0)
        as_field = self.v_target_unit.get() == "T"
        if as_field and not self.calibration.is_measured and not messagebox.askyesno(
                "No calibration",
                "There is no saved calibration, so tesla is converted with a rough "
                f"default ({self.calibration.slope:g} T/A).\n\nContinue anyway?"):
            return
        if as_field and self.cal_candidate is not None:
            self.log("Note: using the ACTIVE calibration; the new result on the "
                     "Calibration tab is not saved yet.")
        self._stop_monitor()
        self.worker = SetFieldWorker(self.rig, self.events, self.calibration,
                                     target, as_field,
                                     s.instruments.supply_compliance_v)
        self.worker.start()
        self.var_status.set("Setting field")

    def on_ramp_down(self, degauss: bool) -> None:
        if not self._require_rig():
            return
        self._stop_monitor()
        self.worker = RampDownWorker(self.rig, self.events, degauss=degauss)
        self.worker.start()
        self.var_status.set("Degaussing" if degauss else "Ramping down")

    def on_emergency_stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        if self.rig is not None:
            threading.Thread(target=self.rig.safe_shutdown, daemon=True).start()
        self.log("EMERGENCY STOP -- ramping magnet to zero and disabling output.")
        self.var_status.set("Stopping")

    def on_calibrate(self) -> None:
        if not self._require_rig():
            return
        s = self._collect_settings()
        if self.cal_candidate is not None and not messagebox.askyesno(
                "Unsaved result",
                "There is a new calibration you have not saved. Discard it and "
                "run another?"):
            return
        self._stop_monitor()
        self.cal_candidate = None
        self._refresh_calibration_labels()
        self.worker = CalibrationWorker(
            self.rig, self.events, self.base_dir,
            _to_float(self.v_cal_start.get(), -10.0),
            _to_float(self.v_cal_stop.get(), 10.0),
            _to_float(self.v_cal_step.get(), 0.2),
            _to_float(self.v_cal_settle.get(), 0.5),
            s.instruments.supply_compliance_v)
        self.worker.start()
        self.var_status.set("Calibrating")

    def on_change_data_dir(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("Busy", "Wait for the current operation to finish.")
            return
        path = filedialog.askdirectory(initialdir=str(self.base_dir),
                                       title="Choose the data folder")
        if not path:
            return
        self.base_dir = Path(path)
        self.data_source = "local_config.yaml"
        save_data_dir(self.base_dir)
        self.v_datadir.set(str(self.base_dir))
        self.calibration = Calibration.load(self.base_dir / CALIBRATION_FILE)
        self.cal_candidate = None
        self._refresh_calibration_labels()
        self.log(f"Data folder set to {self.base_dir} (remembered on this machine).")
        self._log_active_calibration()

    def on_load_cal(self) -> None:
        start = self.base_dir / HISTORY_DIR
        path = filedialog.askopenfilename(
            initialdir=str(start if start.exists() else self.base_dir),
            title="Load a calibration",
            filetypes=[("Calibration", "*.json *.csv"), ("JSON", "*.json"),
                       ("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            cand = Calibration.from_file(Path(path))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not load calibration", str(exc))
            self.log(f"Load failed for {Path(path).name}: {exc}")
            return
        if not cand.is_measured:
            messagebox.showerror("Could not load calibration",
                                 f"{Path(path).name} does not contain a fitted calibration.")
            return
        self.cal_candidate = cand
        self._refresh_calibration_labels()
        self.log(f"Loaded {Path(path).name}: {cand.describe()} -- "
                 f"review, then 'Save as active' to use it.")

    def on_save_candidate(self) -> None:
        cand = self.cal_candidate
        if cand is None:
            return
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("Busy", "Wait for the current operation to finish.")
            return
        old = self.calibration
        if not messagebox.askyesno(
                "Replace active calibration?",
                f"Current:  {old.describe()}\n"
                f"New:      {cand.describe()}\n\n"
                f"{cand.compare(old)}\n\n"
                f"The current file is kept in {HISTORY_DIR}/ and can be loaded back."):
            return
        try:
            backup = save_as_active(cand, self.base_dir)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return
        self.calibration = Calibration.load(self.base_dir / CALIBRATION_FILE)
        self.cal_candidate = None
        self._refresh_calibration_labels()
        self.log(f"Active calibration updated: {self.calibration.describe()}")
        if backup is not None:
            self.log(f"Previous calibration kept as {HISTORY_DIR}/{backup.name}")

    def on_discard_candidate(self) -> None:
        if self.cal_candidate is None:
            return
        self.cal_candidate = None
        self._refresh_calibration_labels()
        self.log("New calibration discarded; active calibration unchanged.")

    def on_open_cal_folder(self) -> None:
        folder = self.base_dir / HISTORY_DIR
        folder.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows
        except Exception:  # noqa: BLE001
            self.log(f"Calibration history: {folder}")

    # ---------------------------------------------------------- field monitor

    def _start_monitor(self) -> None:
        self._monitor_stop.clear()

        def poll():
            while not self._monitor_stop.is_set():
                try:
                    if self.rig is not None:
                        self.events.put(("monitor", self.rig.read_field()))
                except Exception:
                    pass
                time.sleep(1.0)

        self._monitor = threading.Thread(target=poll, daemon=True)
        self._monitor.start()

    def _stop_monitor(self) -> None:
        self._monitor_stop.set()
        self._monitor = None

    # ------------------------------------------------------------ event pump

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self._pump_id = self.after(100, self._drain_events)

    def _handle(self, kind: str, payload) -> None:
        if kind == "log":
            self.log(payload)

        elif kind == "monitor":
            self.var_field.set(f"field {payload:+.5f} T")

        elif kind == "progress":
            p = payload
            done = p.freq_index * p.point_total + p.point_index
            total = p.freq_total * p.point_total
            self.pbar["value"] = 100.0 * done / max(total, 1)
            self.v_prog_text.set(
                f"{p.frequency_hz / 1e9:.3f} GHz ({p.freq_index + 1}/{p.freq_total})"
                f"   pt {p.point_index}/{p.point_total}   ETA {_hms(p.eta_s)}")

        elif kind == "trace":
            frequency, fields, volx, voly = payload
            r = np.hypot(np.asarray(volx), np.asarray(voly)) * 1e6
            self.ax.clear()
            self.ax.plot(fields, r, lw=1.1, color=ACCENT,
                         label=f"{frequency / 1e9:g} GHz")
            self.ax.set_xlabel("Magnetic field (T)")
            self.ax.set_ylabel("Lock-in R (uV)")
            self.ax.set_title("Live trace")
            self.ax.grid(alpha=0.3)
            self.ax.legend(loc="best", fontsize=9)
            self.canvas.draw_idle()
            if fields:
                self.var_field.set(f"field {fields[-1]:+.5f} T")

        elif kind == "cal_points":
            self._draw_calibration_plot(live_points=payload)

        elif kind == "cal_progress":
            i, n = payload
            self.v_prog_text.set(f"Calibrating {i}/{n}")

        elif kind == "cal_done":
            # A fresh run never replaces the active calibration on its own.
            self.cal_candidate = payload
            self._refresh_calibration_labels()
            self.nb.select(self.tab_cal)

        elif kind == "field_step":
            self.v_prog_text.set(f"Ramping: {payload:+.2f} A")

        elif kind == "lockin_applied":
            self.settings.lockin = payload
            self.v_sens.set(payload.sensitivity_tag)
            self.v_tc.set(f"{payload.time_constant_s:g}")

        elif kind == "finished":
            self.pbar["value"] = 100
            self.v_prog_text.set(f"Done -- {payload} files written.")
            messagebox.showinfo("Sweep complete", f"{payload} frequencies saved.")

        elif kind == "aborted":
            self.v_prog_text.set(f"Stopped after {payload} files.")

        elif kind == "error":
            self.v_prog_text.set("Error -- see log.")
            messagebox.showerror("Instrument error", str(payload))

        elif kind == "idle":
            self.worker = None
            self.btn_start.configure(state="normal")
            self.btn_pause.configure(state="disabled", text="Pause")
            self.btn_stop.configure(state="disabled")
            if self.rig is not None:
                self.var_status.set("SIMULATED" if self.settings.instruments.simulate
                                    else "Connected")
                self._start_monitor()

    # ---------------------------------------------------------------- close

    def destroy(self) -> None:
        try:
            self.after_cancel(self._pump_id)
        except Exception:  # noqa: BLE001
            pass
        super().destroy()

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno(
                    "Still running",
                    "An operation is running. Stop it, ramp the magnet down "
                    "and quit?"):
                return
            self.worker.stop()
            self.worker.join(timeout=20)
        if self.cal_candidate is not None:
            answer = messagebox.askyesnocancel(
                "Unsaved calibration",
                f"New calibration not saved:\n{self.cal_candidate.describe()}\n\n"
                f"Save it as the active calibration before quitting?\n"
                f"(No keeps the current one.)")
            if answer is None:
                return
            if answer:
                save_as_active(self.cal_candidate, self.base_dir)
        self._stop_monitor()
        if self.rig is not None:
            self.rig.close()
        self.destroy()


def _cal_block(c: Calibration) -> str:
    if not c.is_measured:
        return (f"slope      {c.slope:.6g} T/A\n"
                f"intercept  {c.intercept:+.5g} T\n"
                f"(default estimate -- not measured)")
    src = Path(c.source).name if c.source else "-"
    if len(src) > 26:
        src = src[:12] + "..." + src[-11:]
    return (f"slope      {c.slope:.6g} T/A\n"
            f"intercept  {c.intercept:+.5g} T\n"
            f"R-squared  {c.r_squared:.5f}\n"
            f"points     {c.n_points}  ({c.current_range_a[0]:g} .. "
            f"{c.current_range_a[1]:g} A)\n"
            f"measured   {c.created.replace('T', ' ')}\n"
            f"source     {src}")


def _to_float(text: str, default: float) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def _sensitivity_from_tag(tag: str) -> float:
    for value in SENSITIVITIES:
        if format_sensitivity(value) == tag:
            return value
    return 500e-6


def _hms(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h{m:02d}m" if h else f"{m:d}m{s:02d}s"


def main(base_dir: Path | None = None, source: str = "default") -> None:
    if base_dir is None:
        from .paths import resolve_data_dir
        base_dir, source = resolve_data_dir()
    app = FMRApp(Path(base_dir), source)
    app.mainloop()
