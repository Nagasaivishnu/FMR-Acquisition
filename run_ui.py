"""Launch the FMR acquisition UI.

    python run_ui.py
    python run_ui.py --data-dir "C:\\Users\\Simulation\\Documents\\Test\\FMR"

Run folders, the magnet calibration file and saved configs go under the data
folder -- see fmrui/paths.py for how it is chosen. You can also change it from
the Sweep tab; the choice is remembered in local_config.yaml (not committed).
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fmrui.app import main  # noqa: E402
from fmrui.paths import resolve_data_dir  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FMR acquisition UI")
    parser.add_argument("--data-dir", help="folder for run output and calibration")
    args = parser.parse_args()
    data_dir, source = resolve_data_dir(args.data_dir)
    main(base_dir=data_dir, source=source)
