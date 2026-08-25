# xaeian/extras.py

"""
Signal for a feature whose optional dependency is not installed.

A module that needs an extra converts the missing import into `MissingExtra`,
and a package `__init__` catches exactly that and leaves the feature out.

Anything else raised while importing the module is a real fault,
and reaches the caller with its traceback intact.

Example:
  >>> try:
  ...   import paramiko
  ... except ModuleNotFoundError as e:
  ...   if not absent(e, "paramiko"): raise
  ...   raise MissingExtra("Install with: pip install xaeian[sftp]") from e
"""

class MissingExtra(ImportError):
  """An optional dependency is missing; the message names the install command."""

def absent(err:ModuleNotFoundError, *packages:str) -> bool:
  """
  Is `err` one of `packages` not being installed, rather than a fault inside an installed one?

  An installed package whose own imports are broken raises `ModuleNotFoundError` too,
  and answering that with "install the extra" sends the user to reinstall what they already have.
  """
  name = err.name or ""
  return any(name == p or name.startswith(f"{p}.") for p in packages)
