"""Isolate this suite from the invoking user's live Kilix store and XDG dirs.

Store roots used by tests come from explicit temp directories. XDG_* and
KILIX_* are redirected here so an import cannot fall back to the NSS home.
The live store under the NSS home is never opened.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SUPPORT = Path(__file__).resolve().parent / "support"
if str(_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_SUPPORT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="kilix-license-suite-"))

for _key, _name in (
    ("XDG_CACHE_HOME", "xdg-cache"),
    ("XDG_CONFIG_HOME", "xdg-config"),
    ("XDG_DATA_HOME", "xdg-data"),
    ("XDG_STATE_HOME", "xdg-state"),
    ("XDG_RUNTIME_DIR", "xdg-runtime"),
    ("KILIX_DATA_HOME", "kilix-data"),
    ("KILIX_STORAGE_HOME", "kilix-storage"),
    ("KILIX_HOME", "kilix-home"),
    ("GPU_TERMINAL_HOME", "gpu-terminal"),
    ("CANDIDATE_SCRATCH_ROOT", "candidate"),
):
    _path = _SCRATCH / _name
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_key] = str(_path)

# Load the live-store guard when tests/support is on sys.path (sitecustomize
# already ran for `python -m unittest`; this covers `python tests/foo.py`).
try:
    from live_store_guard import install as _install_live_store_guard
except ImportError:
    pass
else:
    _install_live_store_guard()
