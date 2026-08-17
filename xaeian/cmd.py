# xaeian/cmd.py

"""
Shell command helpers: version check, execution, lookup.

Thin wrappers over `subprocess` and `shutil.which`: `version`, `which` and `output` return
`None` when a command is missing or fails, `run` returns the raw `CompletedProcess`.
"""

import os, re, shlex, subprocess, shutil
from typing import Sequence

#------------------------------------------------------------------------------------------ Version

def version(cmd:str, args:Sequence[str]=("--version",)) -> str|None:
  """
  First version-like token (`1.2.3`) in the command's stdout or stderr, exit status ignored.

  A leading `v` is part of the token, so `node` yields `v22.1.0`, not `22.1.0`.
  """
  try:
    proc = subprocess.run([cmd, *args], capture_output=True, text=True, check=False)
  except OSError:
    return None
  output = (proc.stdout or "") + (proc.stderr or "")
  match = re.search(r"\bv?\d+(?:\.\d+){1,3}(?:[-_\w]*)?\b", output)
  return match.group(0) if match else None

#------------------------------------------------------------------------------------------- Lookup

def exists(cmd:str) -> bool:
  """Check if command is available on PATH."""
  return shutil.which(cmd) is not None

def which(*cmds:str) -> str|None:
  """Full path of the first candidate found on PATH."""
  for cmd in cmds:
    path = shutil.which(cmd)
    if path: return path
  return None

#------------------------------------------------------------------------------------------ Execute

def _split(cmd:str) -> list[str]:
  """`shlex.split` with POSIX rules; on Windows backslashes are pre-escaped, so paths survive."""
  if os.name == "nt": cmd = cmd.replace("\\", "\\\\")
  return shlex.split(cmd)

def output(cmd:str|list[str], cwd:str|None=None, encoding:str="utf-8") -> str|None:
  """Stripped stdout, `None` on non-zero exit or when the command cannot be launched."""
  if isinstance(cmd, str): cmd = _split(cmd)
  try:
    proc = subprocess.run(
      cmd, capture_output=True, text=True,
      cwd=cwd, encoding=encoding, check=False,
    )
  except OSError:
    return None
  if proc.returncode != 0: return None
  return proc.stdout.strip()

def run(
  cmd:str|list[str],
  cwd:str|None = None,
  env:dict|None = None,
  capture:bool = True,
  check:bool = False,
  encoding:str = "utf-8",
  timeout:float|None = None,
) -> subprocess.CompletedProcess:
  """
  Run command in text mode, capturing output and tolerating a non-zero exit.

  Args:
    env: Merged over `os.environ` rather than replacing it.
    check: Raise `CalledProcessError` on non-zero exit.
    timeout: Seconds before `subprocess.TimeoutExpired`, `None` = no limit.
  """
  if isinstance(cmd, str): cmd = _split(cmd)
  merged_env = {**os.environ, **env} if env else None
  return subprocess.run(
    cmd, capture_output=capture, text=True,
    cwd=cwd, env=merged_env, check=check, encoding=encoding, timeout=timeout,
  )
