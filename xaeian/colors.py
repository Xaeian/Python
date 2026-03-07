# xaeian/colors.py

import builtins

"""
ANSI color codes for terminal output.

Provides `Color` class with 256-color ANSI escape sequences
and `Ico` class with pre-formatted log level indicators.

Example:
  >>> print(f"{Color.RED}Error!{Color.END}")
  Error!  # displayed in red
  >>> print(f"{Ico.ERR} Something failed")
  ERR Something failed  # ERR in red
"""

class Color:
  """
  ANSI 256-color escape sequences.

  Use `Color.END` to reset formatting after colored text.

  Example:
    >>> print(f"{Color.GREEN}Success{Color.END}")
    Success  # displayed in green
    >>> msg = f"{Color.YELLOW}Warning:{Color.END} check config"
  """
  MAROON  = "\033[38;5;88m"   # 870000
  RED     = "\033[38;5;167m"  # D75F5F
  SALMON  = "\033[38;5;181m"  # D7AFAF
  ORANGE  = "\033[38;5;173m"  # D7875F
  GOLD    = "\033[38;5;178m"  # D7AF00
  YELLOW  = "\033[38;5;227m"  # FFFF5F
  CREAM   = "\033[38;5;187m"  # D7D7AF
  LIME    = "\033[38;5;112m"  # 87D700
  GREEN   = "\033[38;5;71m"   # 5FAF5F
  TURQUS  = "\033[38;5;79m"   # 5FD7AF
  TEAL    = "\033[38;5;37m"   # 00AFAF
  CYAN    = "\033[38;5;44m"   # 00D7D7
  SKY     = "\033[38;5;75m"   # 5FAFFF
  BLUE    = "\033[38;5;69m"   # 5F87FF
  VIOLET  = "\033[38;5;99m"   # 875FFF
  PURPLE  = "\033[38;5;134m"  # AF5FD7
  MAGNTA  = "\033[38;5;170m"  # D75FD7
  PINK    = "\033[38;5;168m"  # D75F87
  GREY    = "\033[38;5;240m"  # 585858
  SILVER  = "\033[38;5;248m"  # A8A8A8
  WHITE   = "\033[97m"
  END     = "\033[0m"

class Ico:
  """
  Pre-formatted log level indicators with colors.

  Ready-to-use colored prefixes for log messages.
  Use `GAP` for alignment when no icon needed.

  Example:
    >>> print(f"{Ico.INF} Starting server...")
    INF Starting server...  # INF in blue
    >>> print(f"{Ico.ERR} Connection failed")
    ERR Connection failed   # ERR in red
  """
  INF = f"{Color.SILVER}INF{Color.END}"
  ERR = f"{Color.RED}ERR{Color.END}"
  WRN = f"{Color.YELLOW}WRN{Color.END}"
  OK =  f"{Color.GREEN}OK{Color.END}"
  TIP = f"{Color.VIOLET}TIP{Color.END}"
  RUN = f"{Color.BLUE}RUN{Color.END}"
  DOT = f"{Color.SILVER} • {Color.END}"
  GAP = "   "

class Print:
  def __init__(self, file=None):
    self._file = file

  def __call__(self, *args, **kwargs):
    if self._file and "file" not in kwargs:
      kwargs["file"] = self._file
    builtins.print(*args, **kwargs)

  def _pre(self, ico, *args, **kwargs):
    self(ico, *args, **kwargs)

  def inf(self, *args, **kwargs): self._pre(Ico.INF, *args, **kwargs)
  def err(self, *args, **kwargs): self._pre(Ico.ERR, *args, **kwargs)
  def wrn(self, *args, **kwargs): self._pre(Ico.WRN, *args, **kwargs)
  def tip(self, *args, **kwargs): self._pre(Ico.TIP, *args, **kwargs)
  def run(self, *args, **kwargs): self._pre(Ico.RUN, *args, **kwargs)
  def dot(self, *args, **kwargs): self._pre(Ico.DOT, *args, **kwargs)
  def gap(self, *args, **kwargs): self._pre(Ico.GAP, *args, **kwargs)
  def ok(self, *args, **kwargs):
    suffix = f" {Ico.OK}"
    if args:
      last = str(args[-1]) + suffix
      args = (*args[:-1], last)
    else:
      args = (suffix.lstrip(),)
    self._pre(Ico.INF, *args, **kwargs)

def test_colors():
  """Display all available colors in terminal."""
  samples = [
    ("MAROON",  Color.MAROON),
    ("RED",     Color.RED),
    ("SALMON",  Color.SALMON),
    ("ORANGE",  Color.ORANGE),
    ("GOLD",    Color.GOLD),
    ("YELLOW",  Color.YELLOW),
    ("CREAM",   Color.CREAM),
    ("LIME",    Color.LIME),
    ("GREEN",   Color.GREEN),
    ("TURQUS",  Color.TURQUS),
    ("TEAL",    Color.TEAL),
    ("CYAN",    Color.CYAN),
    ("SKY",     Color.SKY),
    ("BLUE",    Color.BLUE),
    ("VIOLET",  Color.VIOLET),
    ("PURPLE",  Color.PURPLE),
    ("MAGNTA",  Color.MAGNTA),
    ("PINK",    Color.PINK),
    ("GREY",    Color.GREY),
    ("SILVER",  Color.SILVER),
    ("WHITE",   Color.WHITE),
  ]
  for name, code in samples:
    colored = f"{code}{name:8}{Color.END}"
    literal = code.replace("\033", r"\033")
    print(f"{colored}{literal:15}")

if __name__ == "__main__":
  test_colors()
