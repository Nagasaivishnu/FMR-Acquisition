# Bugs found in the existing acquisition scripts, and how this project handles them

Scope is acquisition only — `FMR.py` (the `py_fmr` loop), `set_field.py`,
`calibrate_power_supply`, `lock_in_amp.py`, `power_supply.py`, `gaussmeter.py`.
The old files are kept unmodified in `legacy/`; `fmrui/` is a parallel implementation.

Analysis-side bugs (phase-rotation convention, index-aligned background
subtraction, unequal sweep lengths in `process_fmr_data.py`) are listed at the
end but are **not** fixed here, because they live in code this project does not
replace.

---

## 1. The logged current is one step ahead of the measurement

`FMR.py`, both branches of the sweep loop:

```python
powersupply.current_setpoint = curr
time.sleep(0.3)
curr = curr - curr_interval   # advanced BEFORE the reading is stored
volx.append(lockinamp.x)
currs.append(curr)            # so this is the NEXT setpoint, not this one
```

The voltages and the field are read at setpoint `curr`, but the value written
to the `Current` column is `curr - interval`. Every row is off by exactly one
step. You can see it in the archive: `Py_vishnu_Antidot_reverse_sweep1` has
`range_min: 15` in the config and `Current = 14.98` on the first data row.

**Impact:** low but real. Your analysis keys off the measured `field` column,
which is correct, so published numbers are unaffected. Anyone who plots against
`Current`, or reconstructs field from current via the calibration, picks up a
0.02 A (~0.5 mT) systematic shift.

**Fix:** `acquisition.py` builds the setpoint array up front and appends the
setpoint that was actually applied for that reading.
`selftest.py` asserts the first and last logged currents equal the requested
start and stop.

## 2. The field step drifts, and the endpoint is missed

`while curr <= curr_range_max: curr = curr + curr_interval` accumulates
floating-point error over 1500 iterations, and the loop stops on whichever side
of the limit the accumulation lands — the requested endpoint is not guaranteed
to be measured.

**Fix:** `field_setpoints()` uses `np.linspace` with a computed point count.
Both endpoints are hit exactly and every step is identical.

## 3. X and Y are sampled at different times

```python
volx.append(lockinamp.x)   # one GPIB round trip
voly.append(lockinamp.y)   # another, tens of ms later
```

Two separate `OUTP?` queries are two separate conversions. The field is moving
between them, so X and Y describe slightly different field points — which
matters precisely because every downstream script combines them into
`R = sqrt(X² + Y²)` or rotates by `arctan2(Y, X)`.

**Fix:** `Rig.read_xy()` uses the SR830 `SNAP` command, which returns X and Y
from one conversion. Falls back to separate reads if `snap` is unavailable.

## 4. Sensitivity was never applied, but was still in the filename

In `FMR.py`:

```python
#lockinamp.sensitivity = lockin_sens
```

Commented out. Meanwhile filenames carry `_500uV_`, `_100uV_`, `_1mV_` etc.,
typed by hand into `smaple_identity`. Nothing connects the label to the
instrument, so a forgotten front-panel change silently mislabels a whole run —
and since sensitivity was recorded nowhere else, there is no way to audit it
afterwards.

**Fix:** the UI programs sensitivity, time constant, phase and filter slope,
snaps each to the nearest value the SR830 supports, reports what was actually
applied, and *derives* the filename tag from that applied value. The tag cannot
disagree with the instrument.

## 5. Nothing ramps the magnet down on an error

`py_fmr` has no `try/finally`. A VISA timeout, a bad frequency, or Ctrl-C at
the wrong moment leaves the Kepco energised at up to 15 A with nobody watching.
`set_field.py` ends with `time.sleep(5*60)` and a printed "please remove the
sample" — the magnet is off there, but only if the script reaches that line.

**Fix:** every worker thread ends in a `finally` that ramps to zero and
disables the output. Closing the window mid-run does the same. There is a red
**STOP / magnet off** button on the Field tab that works during any operation.

## 6. The magnet is stepped from 0 A straight to the sweep start

```python
powersupply.current_setpoint = curr_range_min   # 0 -> 15 A in one command
```

A 15 A step into an inductive load, with a 14 V compliance.

**Fix:** `Rig.ramp_current()` walks to any target in bounded steps (default
0.25 A) with a settle delay, and is used for the initial approach, for the
return to the sweep start between frequencies, and for shutdown.

## 7. Re-running a measurement silently overwrote the previous one

The filename is a pure function of the settings, and `open(path, 'w')`
truncates. Repeat a frequency with the same settings — a common thing to do
when a trace looks wrong — and the earlier file is gone.

**Fix:** `unique_path()` adds a `_run2`, `_run3`, ... suffix. The UI also warns
before starting into a folder that already contains FMR CSVs.

## 8. Run conditions were not recorded anywhere

Sensitivity, time constant, settle time, the calibration in force, instrument
identities, start time — none of it is in the CSV or anywhere else. Only what
fits in the filename survives.

**Fix:** a sidecar `<prefix>_run_metadata.json` per run. It is deliberately
*not* embedded as a comment header in the CSV, because the existing scripts
call `pd.read_csv` without `comment=`, and a header line would break every one
of them.

## 9. Gaussmeter port differed between scripts

`FMR.py` and `set_field.py` use `COM4`; `calibrate_power_supply.set_field` uses
`COM5` while `calibrate_power_supply.calibrate_magnetic_field` uses `COM4` —
in the same file.

**Fix:** one address list on the Instruments tab, used by every tab.

## 10. Calibration coefficients were hardcoded literals

```python
curr = (value + 0.0005669588176526382) / 0.024150454853605643
# curr = (value - 0.0012445741735022864)/0.024277877075667934   <- previous fit
```

The active calibration is a magic number in the source with an older one
commented out beside it, and no record of which sweep produced either.

**Fix:** the Calibration tab fits the sweep and writes
`magnet_calibration.json` with slope, intercept, R², point count, current range
and timestamp. The Field tab shows which calibration it is using and when it
was taken.

## 11. `calibrate_power_supply` cannot be imported

No `.py` extension, so it can only be run by path — never imported or reused.

**Fix:** the calibration lives in `fieldtools.CalibrationWorker`.

## 12. The calibration CSV header had no line ending

```python
file.write("field,AppliedCurrent,MeasureCurrent")   # no \n
for ...:
    file.write(f"{field[i]}, {currs[i]}, {meas_currs[i]}\n")
```

The first data row is glued onto the header line, so the first point is lost to
`read_csv` and the header is malformed. The values also carry leading spaces,
and the column order in the header (`field, AppliedCurrent, MeasureCurrent`)
does not match what the loop writes.

**Fix:** header terminated properly, no stray spaces, header order matches the
data. `selftest.py` asserts the header is its own line.

## 13. Saved PNGs have no axis labels

`FMR.post_process`:

```python
plt.savefig(f"{str(file_name)[:-4]}.png")
plt.xlabel("current(A)")     # after the save
plt.ylabel("vout (uV)")
plt.legend()
```

`savefig` runs first, so every auto-generated PNG in the archive is unlabelled.
The labels that never made it were also wrong for the plotted data — the x-axis
is `H_field` in tesla, not current in amps.

**Fix:** `save_trace_png()` labels, titles and adds the legend, then saves.
Axis labels match what is plotted (field in T, R in µV).

## 14. Settings that fight each other were not checked

`config.yaml` has `time_contant: 300` — that is an SR830 *index*, not seconds,
and it was never written to the instrument anyway. Nothing warned when the
settle time (0.3 s) was shorter than the time constant, which would make every
reading lag the field.

**Fix:** `Settings.validate()` flags settle < time constant, currents beyond
±20 A, non-positive steps, a stop frequency below the start, and an empty
sample name. Warnings are shown before the run starts, and can be overridden.

## 15. Typo'd config keys

`smaple_identity`, `magnetic_filed_range`, `filed_interval`.

**Fix:** new configs use corrected names; `Settings.from_legacy_yaml` still
reads the old ones so `legacy/config.yaml` loads as-is.

---

## Not fixed here (analysis side, out of scope)

Listed so they are not forgotten:

1. **`process_fmr_data.transform_voltages` uses a meaningless rotation angle.**
   `arctan2(voly.max(), volx.max())` takes two maxima that occur at *different*
   field points. `FMR.post_process` does it correctly — angle at the
   strongest-signal index. Two scripts, two conventions, different results.
2. **Background subtraction aligns by array index, not by field.** `bg_R` is
   padded or truncated to length and subtracted. Sweeps with different point
   counts or start fields subtract misaligned; it should interpolate the
   background onto the sample's field axis.
3. **`save_absorption_data` and the heatmap assume every frequency shares one
   identical field array**, taken from the first frequency. One short sweep
   misaligns or crashes the whole set.
4. **`py_plane_film.py` is dead code** — calls `post_process` with three
   arguments against a two-argument signature and expects a return value the
   function no longer produces. `FullScaleFMR.py` is empty.
