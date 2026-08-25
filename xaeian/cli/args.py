# xaeian/cli/args.py

"""Shared argparse bootstrap for `xn` subcommands."""

import argparse

#------------------------------------------------------------------------------------------- Parser

def _formatter(prog:str) -> argparse.RawDescriptionHelpFormatter:
  return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

class _Parser(argparse.ArgumentParser):
  """Help padded to one blank line above and below, whatever trailing space argparse left."""
  def format_help(self) -> str: return "\n" + super().format_help().rstrip() + "\n\n"

def make_parser(description:str, epilog:str) -> _Parser:
  """Standard `xn` subcommand parser; caller adds its args and `add_help` last."""
  return _Parser(
    description=description,
    formatter_class=_formatter,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=epilog,
  )

def add_help(parser:argparse.ArgumentParser) -> None:
  """Standard `-h`, added last so it lands at the bottom of the options list."""
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

#--------------------------------------------------------------------------------------------- Size

def fmt_size(b:int, units:tuple[str, str, str, str]=(" B", " kB", " MB", " GB")) -> str:
  """Human-readable byte size, 1024-based; each `units` suffix is appended verbatim."""
  if b < 1024: return f"{b}{units[0]}"
  if b < 1024**2: return f"{b/1024:.1f}{units[1]}"
  if b < 1024**3: return f"{b/1024**2:.1f}{units[2]}"
  return f"{b/1024**3:.1f}{units[3]}"
