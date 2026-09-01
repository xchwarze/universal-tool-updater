"""
Shared pytest configuration for the fast pure-unit-test layer.

This is intentionally separate from test/run_pipeline.ps1 (the functional/e2e
battery): nothing here spawns the real CLI, starts an HTTP server, or touches
the network. Every test imports `universal_updater`/`pypdl_extend`/
`UpdateManager` code directly and calls functions/methods in-process, so the
whole suite runs in milliseconds.

`src/` is added to sys.path so `import universal_updater.X`,
`import pypdl_extend...` and `import UpdateManager` resolve the same way they
do for the real application (UpdateManager.py lives directly under src/ and
imports universal_updater.* as top-level packages, not relative imports).
"""

import sys
import pathlib

SRC_PATH = pathlib.Path(__file__).resolve().parents[2] / 'src'
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
