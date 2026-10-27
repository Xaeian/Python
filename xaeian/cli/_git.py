# xaeian/cli/_git.py

"""
Process runner and git queries shared by `xn commit` and `xn release`.

Both go through `gh`: git takes its github.com credentials from it,
so one `gh auth login` serves pushes and releases alike.
The `release@` hash in a release record covers this module and `xn release` alone.
Hence plain `subprocess` rather than `xaeian.cmd`: nothing a release runs lives elsewhere.
"""

import shutil, subprocess, sys
from typing import NoReturn
from ..log import Print
from ..colors import Color as c, fmt_cmd

p = Print()

# by `sys.platform`; any other system takes apt
INSTALL_GH = {
  "win32": "winget install --id GitHub.cli",
  "darwin": "brew install gh",
}

# the empty helper drops whatever git would ask instead, as `gh auth setup-git` writes it
CREDENTIALS = (
  "-c", "credential.https://github.com.helper=",
  "-c", "credential.https://github.com.helper=!gh auth git-credential",
)

class CommandError(Exception):
  """Command missing or failed; its message is what it said, on one line."""

#---------------------------------------------------------------------------------------------- Run

def run(*cmd:str, data:bytes|None=None) -> str:
  """
  `cmd` without a shell, its stdout as text without the last newline.

  `data` goes to stdin as bytes: text mode on Windows turns LF into CRLF,
  and git keeps a message byte for byte.
  Output decodes with `surrogateescape`, so a path goes back to git exactly as it came.
  A failure keeps what the command said, minus git's `hint:` advice and `From`/`To` headers,
  which bury the line saying what went wrong.
  """
  try:
    done = subprocess.run(cmd, input=data, capture_output=True)
  except FileNotFoundError:
    raise CommandError(f"{cmd[0]} not found") from None
  if done.returncode:
    said = (done.stderr or done.stdout).decode("utf-8", "replace").splitlines()
    lines = [line.strip() for line in said if not line.startswith(("hint:", "From ", "To "))]
    raise CommandError(" ".join(line for line in lines if line) or f"{cmd[0]} failed")
  return done.stdout.decode("utf-8", "surrogateescape").removesuffix("\n")

def git(*args:str, data:bytes|None=None) -> str:
  """`git` with `args`, its github.com credentials taken from `gh`."""
  return run("git", *CREDENTIALS, *args, data=data)

def gh(*args:str, data:bytes|None=None) -> str:
  """GitHub CLI with `args`."""
  return run("gh", *args, data=data)

def fail(message:str) -> NoReturn:
  """Print `message` as an error and exit 1."""
  p.err(message)
  sys.exit(1)

def github() -> None:
  """`gh` installed and logged in, as both commands need it; else prints the fix and exits 1."""
  if not shutil.which("gh"):
    install = INSTALL_GH.get(sys.platform, "sudo apt install gh")
    p.err(f"Missing {fmt_tool('gh')} tool")
    p.tip(f"Install it with package manager: {fmt_cmd(install)}, then open a new terminal")
    sys.exit(1)
  try:
    gh("auth", "status")
  except CommandError:
    p.err(f"{fmt_tool('gh')} not logged in")
    p.tip(f"Log in once with: {fmt_cmd('gh auth login')}")
    sys.exit(1)

#------------------------------------------------------------------------------------------- Colors

# one color per role, the same in every message of both commands
def fmt_branch(name:str) -> str: return f"{c.VIOLET}{name}{c.END}"
def fmt_release(name:str) -> str: return f"{c.SKY}{name}{c.END}" # version, tag or title
def fmt_sha(commit:str) -> str: return f"{c.GOLD}{commit[:7]}{c.END}"
def fmt_file(path:str) -> str: return f"{c.ORANGE}{path}{c.END}"
def fmt_tool(name:str) -> str: return f"{c.CYAN}{name}{c.END}"

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
