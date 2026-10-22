# xaeian/cli/_git.py

"""
Process runner and git queries shared by `xn commit` and `xn release`.

The `release@` hash in a release record covers this module and `xn release` alone.
Hence plain `subprocess` rather than `xaeian.cmd`: nothing a release runs lives elsewhere.
"""

import subprocess, sys
from typing import NoReturn
from ..log import Print

p = Print()

TARGETS = ("main", "master") # releases land there, `main` first

class CommandError(Exception):
  """A command missing or failed; the message is its stderr when it wrote any."""

#---------------------------------------------------------------------------------------------- Run

def run(*cmd:str, data:bytes|None=None) -> str:
  """
  `cmd` without a shell, its stdout as text without the last newline.

  `data` goes to stdin as bytes: text mode on Windows turns LF into CRLF,
  and git keeps a message byte for byte.
  Output decodes with `surrogateescape`, so a path goes back to git exactly as it came.
  """
  try:
    done = subprocess.run(cmd, input=data, capture_output=True)
  except FileNotFoundError:
    raise CommandError(f"{cmd[0]} not found") from None
  if done.returncode:
    error = done.stderr.decode("utf-8", "replace").strip()
    raise CommandError(error or f"{' '.join(cmd[:2])} failed")
  return done.stdout.decode("utf-8", "surrogateescape").removesuffix("\n")

def git(*args:str, data:bytes|None=None) -> str:
  """`git` with `args`."""
  return run("git", *args, data=data)

def gh(*args:str, data:bytes|None=None) -> str:
  """GitHub CLI with `args`."""
  return run("gh", *args, data=data)

def fail(message:str) -> NoReturn:
  """Print `message` as an error and exit 1."""
  p.err(message)
  sys.exit(1)

#------------------------------------------------------------------------------------------ Queries

def sha(ref:str) -> str|None:
  """Commit `ref` points at, `None` without such a ref."""
  try:
    return git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
  except CommandError:
    return None

def tree(ref:str) -> str:
  """Tree of the commit `ref` points at."""
  return git("rev-parse", f"{ref}^{{tree}}")

def branch() -> str|None:
  """Active branch, `None` on a detached HEAD."""
  try:
    return git("symbolic-ref", "--quiet", "--short", "HEAD")
  except CommandError:
    return None

def config(key:str) -> str:
  """Value of `key` in git config, "" when unset."""
  try:
    return git("config", "--get", key)
  except CommandError:
    return ""
