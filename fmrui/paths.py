"""Where measurement data lives.

The code is a git repository; the data is not. Run folders, the magnet
calibration file and saved configs all go under a *data folder* chosen per
machine, resolved in this order:

1. ``--data-dir`` on the command line
2. the ``FMR_DATA_DIR`` environment variable
3. ``data_dir`` in ``local_config.yaml`` at the repo root (git-ignored; written
   when you pick a folder in the UI)
4. ``<repo>/data`` (git-ignored) as a safe fallback
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = REPO_ROOT / "local_config.yaml"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
ENV_VAR = "FMR_DATA_DIR"


def _read_local() -> dict:
    try:
        with open(LOCAL_CONFIG, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}


def resolve_data_dir(cli_value: str | None = None) -> tuple[Path, str]:
    """Return (data_dir, where_it_came_from)."""
    if cli_value:
        return Path(cli_value).expanduser(), "--data-dir"
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser(), ENV_VAR
    stored = _read_local().get("data_dir")
    if stored:
        return Path(stored).expanduser(), "local_config.yaml"
    return DEFAULT_DATA_DIR, "default"


def save_data_dir(path: Path) -> None:
    """Remember the chosen data folder for this machine only."""
    data = _read_local()
    data["data_dir"] = str(Path(path))
    with open(LOCAL_CONFIG, "w", encoding="utf-8") as fh:
        fh.write("# Machine-specific settings. Not committed (see .gitignore).\n")
        yaml.safe_dump(data, fh, sort_keys=False)
