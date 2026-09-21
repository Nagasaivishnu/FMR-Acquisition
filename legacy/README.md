# Legacy scripts

The original rig scripts, copied unmodified from the lab PC's `FMR` folder so
their history lives in the repo. The UI in `../fmrui/` replaces the
acquisition side of these; the analysis side is still used as-is.

| Script | What it does | Status |
|---|---|---|
| `FMR.py` | frequency x field sweep driven by `config.yaml` | replaced by the UI Sweep tab |
| `set_field.py` | ramp magnet down / hold for sample removal | replaced by the UI Field tab |
| `calibrate_power_supply` | current-to-field calibration (no `.py` extension) | replaced by the UI Calibration tab |
| `pna.py` | PNA as a CW source | still imported by `FMR.py` |
| `lock_in_amp.py`, `power_supply.py`, `gaussmeter.py` | hand-rolled pyvisa wrappers | unused |
| `frequency_spectrum.py` | fixed-field frequency scan | not ported |
| `process_fmr_data.py` | background subtraction, absorption, heatmap | **in use** |
| `absorption.py` | single-file absorption comparison | in use |
| `fit_lorentzian_peaks.py` | multi-peak derivative-Lorentzian fit | in use |
| `plotting.py`, `plottings.py`, `pywire_vs_cowire.py` | Kittel-curve poster figures | in use |
| `py_plane_film.py` | damping fit for the Py film | broken (see `../BUGS_FIXED.md`) |
| `config.yaml` | last acquisition config used on the rig | loads in the UI via Load config |

Things to know before running any of these from here:

- **Paths are hardcoded** to `C:\Users\Simulation\Documents\Test\FMR\...`,
  so the analysis scripts still read from the lab data folder, not the repo.
- **`FMR.py` writes output next to itself** (`Path(__file__).parent`). Run from
  this folder it would create run folders inside the repo; `.gitignore`
  ignores everything in `legacy/` except code, so they won't be committed, but
  prefer the UI for acquisition.
- `FullScaleFMR.py` was an empty file and was not copied.
