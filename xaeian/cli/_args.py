# xaeian/cli/_args.py

"""Shared argparse bootstrap for `xn` subcommands: a terse parser preset and a
size formatter, kept identical across all CLI mains."""

import argparse

#--------------------------------------------------------------------------------------- Parser

def _fmt(prog:str) -> argparse.RawDescriptionHelpFormatter:
  return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

class _Parser(argparse.ArgumentParser):
  # leading blank line + trailing gap for `xn` output
  def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"

def _make_parser(description:str, epilog:str) -> _Parser:
  """Standard `xn` subcommand parser; caller adds its args and `_add_help` last."""
  return _Parser(
    description=description,
    formatter_class=_fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=epilog,
  )

def _add_help(parser:argparse.ArgumentParser) -> None:
  """Standard `-h`, added last so it lands at the bottom of the options list."""
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

#----------------------------------------------------------------------------------------- Size

def _fmt_size(b:int, units:tuple[str, str, str, str]=(" B", " kB", " MB", " GB")) -> str:
  """Human-readable byte size; `units` are full suffixes (incl. any leading space)."""
  if b < 1024: return f"{b}{units[0]}"
  if b < 1024**2: return f"{b/1024:.1f}{units[1]}"
  if b < 1024**3: return f"{b/1024**2:.1f}{units[2]}"
  return f"{b/1024**3:.1f}{units[3]}"
