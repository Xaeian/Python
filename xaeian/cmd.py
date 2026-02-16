# xaeian/cmd.py

"""
Shell command helpers: version check, execution, lookup.
"""

import os, re, shlex, subprocess, shutil
from typing import Sequence

#-------------------------------------------------------------------------------------- Version

def version(cmd:str, args:Sequence[str]=("--version",)) -> str|None:
  """
  Extract version string from command output.

  Args:
    cmd: Executable name or path.
    args: Arguments to print version.

  Returns:
    Version string like "1.2.3" or None.
  """
  try:
    proc = subprocess.run([cmd, *args], capture_output=True, text=True, check=False)
  except OSError:
    return None
  output = (proc.stdout or "") + (proc.stderr or "")
  match = re.search(r"\bv?\d+(?:\.\d+){1,3}(?:[-_\w]*)?\b", output)
  return match.group(0) if match else None

#-------------------------------------------------------------------------------------- Lookup

def exists(cmd:str) -> bool:
  """Check if command is available on PATH."""
  return shutil.which(cmd) is not None

def which(*cmds:str) -> str|None:
  """
  Find first available executable from candidates.

  Args:
    cmds: Candidate executable names.

  Returns:
    Full path to first found executable, or None.
  """
  for cmd in cmds:
    path = shutil.which(cmd)
    if path: return path
  return None

#------------------------------------------------------------------------------------- Execute

def _split(cmd:str) -> list[str]:
  """Split command string respecting quotes and escapes."""
  return shlex.split(cmd, posix=(os.name != "nt"))

def output(cmd:str|list[str], cwd:str|None=None, encoding:str="utf-8") -> str|None:
  """
  Run command and return stdout as string.

  Args:
    cmd: Command string or list.
    cwd: Working directory.
    encoding: Output encoding.

  Returns:
    Stripped stdout or None on failure.
  """
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
  cmd: str|list[str],
  cwd: str|None = None,
  env: dict|None = None,
  capture: bool = True,
  check: bool = False,
  encoding: str = "utf-8",
) -> subprocess.CompletedProcess:
  """
  Run command with sensible defaults.

  Args:
    cmd: Command string or list.
    cwd: Working directory.
    env: Environment variables (merged with os.environ).
    capture: Capture stdout/stderr.
    check: Raise CalledProcessError on non-zero exit.
    encoding: Output encoding.

  Returns:
    CompletedProcess instance.
  """
  if isinstance(cmd, str): cmd = _split(cmd)
  merged_env = None
  if env: merged_env = {**os.environ, **env}
  return subprocess.run(
    cmd, capture_output=capture, text=True,
    cwd=cwd, env=merged_env, check=check, encoding=encoding,
  )