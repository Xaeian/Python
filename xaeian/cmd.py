# xaeian/cmd.py

"""
Shell commands: version check, lookup, a run to its end or in the background.

Thin wrappers over `subprocess` and `shutil.which`:
`version`, `which` and `output` return `None` when a command is missing or fails,
`run` returns the raw `CompletedProcess`, and `start` a process left running, which `stop` ends.
Text decodes as UTF-8, a byte that is no UTF-8 replaced rather than raised.
"""

import os, re, shlex, subprocess, shutil, sys
from typing import Literal, Sequence, overload

#------------------------------------------------------------------------------------------ Version

def version(cmd:str, args:Sequence[str]=("--version",)) -> str|None:
  """
  First version-like token (`1.2.3`) in the command's stdout or stderr, exit status ignored.

  A leading `v` is part of the token, so `node` yields `v22.1.0`, not `22.1.0`.
  """
  try:
    proc = subprocess.run(
      [cmd, *args], capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
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
  if sys.platform == "win32": cmd = cmd.replace("\\", "\\\\")
  return shlex.split(cmd)

def _command(cmd:str|list[str]) -> str|list[str]:
  """
  What `subprocess` takes: a str split as a shell would, a list as it is.
  A Windows batch file runs under cmd, which reads `&` or `|` in a bare argument as its own,
  so every argument goes in quotes, and one holding `"` or `%` is refused: no quote keeps it.
  """
  args = _split(cmd) if isinstance(cmd, str) else list(cmd)
  if sys.platform != "win32" or not args or not args[0].lower().endswith((".bat", ".cmd")):
    return args
  bad = [arg for arg in args if '"' in arg or "%" in arg]
  if bad: raise ValueError(f'A batch file takes no argument holding " or %: {bad[0]}')
  return " ".join(f'"{arg}"' for arg in args)

def output(cmd:str|list[str], cwd:str|None=None, encoding:str="utf-8") -> str|None:
  """Stripped stdout, `None` on non-zero exit or when the command cannot be launched."""
  try:
    proc = subprocess.run(
      _command(cmd), capture_output=True,
      cwd=cwd, encoding=encoding, errors="replace", check=False,
    )
  except OSError:
    return None
  if proc.returncode != 0: return None
  return proc.stdout.strip()

@overload
def run(
  cmd:str|list[str], cwd:str|None = None, env:dict|None = None, capture:bool = True,
  check:bool = False, encoding:str = "utf-8", timeout:float|None = None,
  binary:Literal[False] = False,
) -> subprocess.CompletedProcess[str]: ...
@overload
def run(
  cmd:str|list[str], cwd:str|None = None, env:dict|None = None, capture:bool = True,
  check:bool = False, encoding:str = "utf-8", timeout:float|None = None,
  *, binary:Literal[True],
) -> subprocess.CompletedProcess[bytes]: ...
def run(
  cmd:str|list[str],
  cwd:str|None = None,
  env:dict|None = None,
  capture:bool = True,
  check:bool = False,
  encoding:str = "utf-8",
  timeout:float|None = None,
  binary:bool = False,
) -> subprocess.CompletedProcess:
  """
  Run a command to its end, capturing its output and tolerating a non-zero exit.
  Text decodes with `encoding`, a byte it cannot read replaced; `binary` keeps the bytes.

  Args:
    env: Merged over `os.environ` rather than replacing it.
    check: Raise `CalledProcessError` on non-zero exit.
    timeout: Seconds before `subprocess.TimeoutExpired`, `None` = no limit.
  """
  return subprocess.run(
    _command(cmd), capture_output=capture, cwd=cwd, env={**os.environ, **env} if env else None,
    check=check, timeout=timeout,
    encoding=None if binary else encoding, errors=None if binary else "replace",
  )

#--------------------------------------------------------------------------------------- Background

_STDERR = {"pipe": subprocess.PIPE, "merge": subprocess.STDOUT, "drop": subprocess.DEVNULL}

def start(
  cmd:str|list[str],
  cwd:str|None = None,
  env:dict|None = None,
  stdin:bool = False,
  stderr:Literal["pipe", "merge", "drop"] = "pipe",
  below:bool = False,
  group:bool = False,
) -> subprocess.Popen[bytes]:
  """
  Start a command in the background, its output in pipes of bytes to read as it comes.
  A pipe nobody reads stalls the process once it fills: read it, or `merge` or `drop` stderr.

  Args:
    env: Merged over `os.environ` rather than replacing it.
    stdin: A pipe to write to; without one the process reads nothing, so no prompt hangs it.
    stderr: A `pipe` of its own, `merge` into stdout, or `drop`.
    below: Priority below normal, so the foreground keeps its pace.
    group: A process group of its own: a signal or a Ctrl+Break sent to it reaches it alone,
      and the console's Ctrl+C passes it by.
  """
  if stderr not in _STDERR:
    raise ValueError(f"stderr is one of {', '.join(_STDERR)}, not {stderr!r}")
  flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if below else 0
  if group: flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
  proc = subprocess.Popen(
    _command(cmd), cwd=cwd, env={**os.environ, **env} if env else None,
    stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, stdout=subprocess.PIPE,
    stderr=_STDERR[stderr], creationflags=flags, start_new_session=group,
  )
  if below and sys.platform != "win32": # a niceness of 10 at least, never raised back
    os.setpriority(os.PRIO_PROCESS, proc.pid, max(10, os.getpriority(os.PRIO_PROCESS, proc.pid)))
  return proc

def stop(proc:subprocess.Popen) -> int:
  """
  End `proc` and wait for it, its exit code returned.
  On Windows what it started ends with it, as a `.cmd` runs its Python under cmd and py.
  Elsewhere `proc` alone is killed.
  """
  if proc.poll() is None and sys.platform == "win32":
    tree = ["taskkill", "/PID", str(proc.pid), "/T", "/F"] # its words in the console's code page
    try: subprocess.run(tree, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired): pass
  if proc.poll() is None: proc.kill()
  return proc.wait()
