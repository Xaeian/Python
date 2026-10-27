# xaeian/colors.py

"""
ANSI color codes for terminal output, and the look of a value in a message.

`Color` holds 256-color escape sequences, `Ico` pre-formatted log level tags.
The `fmt_*` functions colour a value by its role, so every tool's lines read alike:
an item's `#id` cream, a path's folder grey, a command as a console shows it.

Example:
  >>> print(f"{Color.RED}Error!{Color.END}")
  >>> print(f"{Ico.ERR} Connection failed")
  >>> print(f"{fmt_id(3, 12)} {fmt_path('out/a.svg')} → {fmt_count(2, 'file')}")
"""

from typing import Sequence
from .files import PATH

class Color:
  """ANSI 256-color escapes, trailing comment is the hex equivalent. `END` resets."""
  MAROON = "\033[38;5;88m"   # 870000
  RED = "\033[38;5;167m"     # D75F5F
  SALMON = "\033[38;5;181m"  # D7AFAF
  ORANGE = "\033[38;5;173m"  # D7875F
  GOLD = "\033[38;5;178m"    # D7AF00
  YELLOW = "\033[38;5;227m"  # FFFF5F
  CREAM = "\033[38;5;187m"   # D7D7AF
  LIME = "\033[38;5;112m"    # 87D700
  GREEN = "\033[38;5;71m"    # 5FAF5F
  TURQUS = "\033[38;5;79m"   # 5FD7AF
  TEAL = "\033[38;5;37m"     # 00AFAF
  CYAN = "\033[38;5;44m"     # 00D7D7
  SKY = "\033[38;5;75m"      # 5FAFFF
  BLUE = "\033[38;5;69m"     # 5F87FF
  VIOLET = "\033[38;5;99m"   # 875FFF
  PURPLE = "\033[38;5;134m"  # AF5FD7
  MAGNTA = "\033[38;5;170m"  # D75FD7
  PINK = "\033[38;5;168m"    # D75F87
  GREY = "\033[38;5;240m"    # 585858
  SILVER = "\033[38;5;248m"  # A8A8A8
  WHITE = "\033[97m"
  END = "\033[0m"

class Ico:
  """Colored log level tags. `GAP` pads a tagless line to tag width."""
  DBG = f"{Color.GREY}DBG{Color.END}"
  INF = f"{Color.BLUE}INF{Color.END}"
  ERR = f"{Color.RED}ERR{Color.END}"
  WRN = f"{Color.YELLOW}WRN{Color.END}"
  CRT = f"{Color.MAGNTA}CRT{Color.END}"
  PNC = f"{Color.GOLD}PNC{Color.END}"
  OK = f"{Color.GREEN}OK{Color.END}"
  TIP = f"{Color.VIOLET}TIP{Color.END}"
  RUN = f"{Color.ORANGE}RUN{Color.END}"
  DOT = f"{Color.SILVER} • {Color.END}"
  GAP = "   "

#--------------------------------------------------------------------------------------------- Look

# a command reads as a console shows it: the program is the one highlight,
# flags and <placeholders> the grey syntax around it; after an operator a new command starts
CMD_OPS = {"|", "||", "&&", ";", "&", ">", ">>"}

def grey(text) -> str:
  """`text` as the ground of a line: a folder, a flag, a note, what did not change."""
  return f"{Color.GREY}{text}{Color.END}"

def fmt_id(n:int, total:int=0) -> str:
  """`#42` in cream, an item's handle, padded to the width of `total` so a batch's lines align."""
  return f"{Color.CREAM}#{n}{Color.END}" + " " * (len(str(total)) - len(str(n)))

def fmt_path(path:str, color:str=Color.BLUE) -> str:
  """A path, relative inside the working folder: its folder grey, its name in `color`."""
  folder, _, name = PATH.local(path).rstrip("/").rpartition("/")
  shown = f"{color}{name}{Color.END}"
  return f"{grey(folder + '/')}{shown}" if folder else shown

def fmt_cmd(cmd:str, ours:Sequence[str]=("xn",)) -> str:
  """A shell command: each program yellow, `ours` gold, flags and <placeholders> grey."""
  out, at_cmd = [], True
  for tok in cmd.split():
    if tok in CMD_OPS:
      out.append(grey(tok))
      at_cmd = True
    elif tok.startswith(("-", "<", "[")):
      out.append(grey(tok))
    elif at_cmd:
      out.append(f"{Color.GOLD if tok in ours else Color.YELLOW}{tok}{Color.END}")
      at_cmd = False
    else:
      out.append(tok)
  return " ".join(out)

def fmt_count(n:int, one:str, many:str|None=None, color:str=Color.BLUE) -> str:
  """`3 files`: the number in `color`, plain when `color` is empty, and the word for it."""
  number = f"{color}{n}{Color.END}" if color else str(n)
  return f"{number} {one if n == 1 else many or one + 's'}"

def fmt_list(names, color:str=Color.SKY) -> str:
  """Names in `color`, joined by commas."""
  return ", ".join(f"{color}{n}{Color.END}" for n in names)

def test_colors() -> None:
  """Print each color name rendered in its own color, next to its escape literal."""
  for name, code in vars(Color).items():
    if not name.isupper() or name == "END": continue
    literal = code.replace("\033", r"\033")
    print(f"{code}{name:8}{Color.END}{literal:15}")

if __name__ == "__main__":
  test_colors()
