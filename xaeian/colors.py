# xaeian/colors.py

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
  RED     = "\033[38;5;167m"  # D75F5F
  GREEN   = "\033[38;5;71m"   # 5FAF5F
  YELLOW  = "\033[38;5;221m"  # FFD75F
  BLUE    = "\033[38;5;69m"   # 5F87FF
  VIOLET  = "\033[38;5;99m"   # 875FFF
  MAGENTA = "\033[38;5;135m"  # AF5FFF
  PINK    = "\033[38;5;168m"  # D75F87
  SALMON  = "\033[38;5;181m"  # D7AFAF
  CYAN    = "\033[38;5;44m"   # 00D7D7
  GOLD    = "\033[38;5;184m"  # D7D700
  ORANGE  = "\033[38;5;173m"  # D7875F
  CREAM   = "\033[38;5;187m"  # D7D7AF
  TEAL    = "\033[38;5;75m"   # 5FAFFF
  TURQUS  = "\033[38;5;79m"   # 5FD7AF
  LIME    = "\033[38;5;112m"  # 87D700
  MAROON  = "\033[38;5;124m"  # AF0000
  GREY    = "\033[38;5;240m"  # 585858
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
  INF = f"{Color.BLUE}INF{Color.END}"
  ERR = f"{Color.RED}ERR{Color.END}"
  WRN = f"{Color.YELLOW}WRN{Color.END}"
  OK  = f"{Color.GREEN}INF{Color.END}"
  TIP = f"{Color.MAGENTA}TIP{Color.END}"
  RUN = f"{Color.ORANGE}RUN{Color.END}"
  GAP = "   "

def test_colors():
  """Display all available colors in terminal."""
  samples = [
    ("RED",     Color.RED),
    ("GREEN",   Color.GREEN),
    ("YELLOW",  Color.YELLOW),
    ("BLUE",    Color.BLUE),
    ("VIOLET",  Color.VIOLET),
    ("MAGENTA", Color.MAGENTA),
    ("PINK",    Color.PINK),
    ("SALMON",  Color.SALMON),
    ("CYAN",    Color.CYAN),
    ("GOLD",    Color.GOLD),
    ("ORANGE",  Color.ORANGE),
    ("CREAM",   Color.CREAM),
    ("TEAL",    Color.TEAL),
    ("TURQUS",  Color.TURQUS),
    ("LIME",    Color.LIME),
    ("MAROON",  Color.MAROON),
    ("GREY",    Color.GREY),
    ("WHITE",   Color.WHITE),
  ]
  for name, code in samples:
    colored = f"{code}{name:8}{Color.END}"
    literal = code.replace("\033", r"\033")
    print(f"{colored}{literal:15}")

if __name__ == "__main__":
  test_colors()
