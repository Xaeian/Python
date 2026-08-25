# tests/test_demos.py

"""
Every module demo runs with one command.

The `__main__` blocks are the library's shortest answer to "how do I use this", so they have
to work. They break silently otherwise: nothing imports them, so a renamed parameter rots
there until someone types the command. Each one runs in a subprocess with stdout redirected,
which is also where the console codepage bites.
"""

import os
import subprocess
import sys
from pathlib import Path
import pytest

DEMOS = [
  "xaeian.colors", "xaeian.crc", "xaeian.cstruct", "xaeian.dsp", "xaeian.plot",
  "xaeian.log", "xaeian.xstring", "xaeian.xtime", "xaeian.files", "xaeian.eda.spice",
]

DRAWS = {"xaeian.plot"}
"""Demos whose output is a figure, not text."""

ROOT = Path(__file__).resolve().parent.parent

@pytest.mark.parametrize("module", DEMOS)
def the_demo_runs_with_one_command(module):
  env = dict(os.environ, PYTHONPATH=str(ROOT), MPLBACKEND="Agg")
  env.pop("PYTHONIOENCODING", None) # the redirected console is the case that used to fail
  done = subprocess.run([sys.executable, "-m", module], capture_output=True, text=True,
    env=env, cwd=str(ROOT), timeout=120)
  assert done.returncode == 0, f"{module} exited {done.returncode}:\n{done.stderr[-800:]}"
  if module not in DRAWS:
    assert done.stdout.strip(), f"{module} printed nothing"
