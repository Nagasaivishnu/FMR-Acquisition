# FMR-Acquisition

A small Tkinter front end for the FMR rig: frequency-swept acquisition, magnet
set-field and degauss, and current-to-field calibration.

It writes files in exactly the format the existing analysis scripts
(`legacy/process_fmr_data.py`, `legacy/absorption.py`, ...) already read, so
they work on new runs with no changes.

```
FMR-Acquisition/
├── run_ui.py            <- start here
├── selftest.py          <- headless check, no hardware needed
├── requirements.txt
├── BUGS_FIXED.md        <- what changed relative to the old scripts, and why
├── fmrui/
│   ├── settings.py      run parameters, YAML load/save, filenames
│   ├── instruments.py   PNA + SR830 + Kepco + LakeShore (and a simulator)
│   ├── acquisition.py   the sweep worker thread
│   ├── fieldtools.py    set-field, degauss, calibration
│   ├── paths.py         where the data folder is
│   └── app.py           the Tkinter window
└── legacy/              <- the original rig scripts, unmodified
```

## Install

```
git clone https://github.com/Nagasaivishnu/FMR-Acquisition.git
cd FMR-Acquisition
pip install -r requirements.txt
```

## Run

```
python run_ui.py
```

## Data folder

Code lives in the repo; measurement data does not. Run folders,
`magnet_calibration.json` and saved configs go into a **data folder** chosen
per machine, looked up in this order:

1. `python run_ui.py --data-dir "C:\Users\Simulation\Documents\Test\FMR"`
2. the `FMR_DATA_DIR` environment variable
3. `local_config.yaml` in the repo root — written when you click
   **Change...** next to "Data folder" on the Sweep tab (git-ignored)
4. `data/` inside the repo (git-ignored) if nothing else is set

On the lab PC, click **Change...** once and pick the existing `FMR` folder;
new runs then land next to the old ones and the saved calibration is picked up.
The log shows which folder is in use at startup.

## Try it without hardware

Instruments tab -> tick **Simulate** -> Connect. A synthetic sample with a
Kittel-like resonance responds to the sweep, so you can lay out a run, check
the filenames and watch the live plot from any machine.

## The four tabs

**Sweep** — the whole run in one form: sample identity, output folder,
microwave start/stop/step and power, field start/stop/step and settle time,
and every lock-in setting. The summary line above the plot tells you how many
files the run will produce and roughly how long it will take, before you start.
Start / Pause / Resume / Stop are always visible at the bottom left. The plot
shows the trace for the frequency currently being measured.

**Field** — go to a target field (in tesla, converted through the saved
calibration, or in raw amps) and hold there while you mount or inspect a
sample. "Degauss + ramp down" walks a decaying alternating current to zero to
clear remanence before you remove the sample. The red button aborts anything
running and takes the magnet to zero.

**Calibration** — the field tab converts tesla to amps with the *active*
calibration, `magnet_calibration.json` in the data folder. It is loaded
automatically at every start, so once saved you keep using it until you
decide otherwise.

To change it, get a new result one of two ways:

- **Run calibration** — sweeps the current, logs the gaussmeter and fits
  `field = slope x current + intercept`.
- **Load from file...** — a calibration `.json` (any earlier run in
  `calibrations/`) or a `.csv` of current and field. The old
  `calibrated_data_*.csv` files load too, including the ones whose header
  swallowed the first data row.

The new result is shown next to the active one, plotted against it, with the
difference (slope %, and mT at 10 A). Nothing changes until you click
**Save as active**; **Discard** keeps what you had. Replacing the active file
copies the old one into `calibrations/` first, and every run is archived
there (`.csv` + `.json` + `.png`) whether you save it or not — so any earlier
calibration can always be loaded back. Quitting with an unsaved result asks
what to do.

**Instruments** — every VISA address in one place, plus Connect/Disconnect and
the `*IDN?` responses.

## Output

Per frequency, into the folder named on the Sweep tab:

```
<sample>_<sensitivity>_FMR_mmWave<f>GHz_power<p>dBm_lockin_amp<a>V_freq_<ref>_filter_<slope>.csv
<same>.png
```

The CSV has exactly the four legacy columns, `Current,field,voltageX,voltageY`,
and no comment header, so `pd.read_csv` in the existing scripts still works.

Everything that used to be unrecorded — sensitivity, time constant, settle
time, instrument IDs, the frequency list, start time — goes into a sidecar
`<sample>_<sensitivity>_run_metadata.json` in the same folder. It does not
match the `*FMR*.csv` glob, so it is invisible to the analysis scripts.

Existing files are never overwritten: a clashing name gets a `_run2` suffix.

## Configs

Save / Load on the Sweep tab reads and writes YAML. The old
`legacy/config.yaml` loads too — the `smaple_identity`, `magnetic_filed_range` and
`filed_interval` keys are handled, and the numeric `sens` / `time_contant`
indices are translated into real volts and seconds.

## Check it works

```
python selftest.py
```

Runs a simulated sweep and a simulated calibration, then asserts the outputs
are readable by the existing analysis code. No hardware, no GUI.
Run it before committing changes to `fmrui/`.

## Safety

Every worker ramps the magnet to zero and disables the output in a `finally`
block, so an instrument error, a Stop, or closing the window cannot leave the
supply energised. Current setpoints beyond +/-20 A are refused. The magnet is
walked to the sweep start in bounded steps rather than jumping there.
