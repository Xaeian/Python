# xaeian/colors.py

"""
ANSI color codes for terminal output.

`Color` holds 256-color escape sequences, `Ico` pre-formatted log level tags.

Example:
  >>> print(f"{Color.RED}Error!{Color.END}")
  >>> print(f"{Ico.ERR} Connection failed")
"""

class Color:
  """ANSI 256-color escapes, trailing comment is the hex equivalent. `END` resets."""
  MAROON = "\033[38;5;88m"  # 870000
  RED = "\033[38;5;167m"    # D75F5F
  SALMON = "\033[38;5;181m" # D7AFAF
  ORANGE = "\033[38;5;173m" # D7875F
  GOLD = "\033[38;5;178m"   # D7AF00
  YELLOW = "\033[38;5;227m" # FFFF5F
  CREAM = "\033[38;5;187m"  # D7D7AF
  LIME = "\033[38;5;112m"   # 87D700
  GREEN = "\033[38;5;71m"   # 5FAF5F
  TURQUS = "\033[38;5;79m"  # 5FD7AF
  TEAL = "\033[38;5;37m"    # 00AFAF
  CYAN = "\033[38;5;44m"    # 00D7D7
  SKY = "\033[38;5;75m"     # 5FAFFF
  BLUE = "\033[38;5;69m"    # 5F87FF
  VIOLET = "\033[38;5;99m"  # 875FFF
  PURPLE = "\033[38;5;134m" # AF5FD7
  MAGNTA = "\033[38;5;170m" # D75FD7
  PINK = "\033[38;5;168m"   # D75F87
  GREY = "\033[38;5;240m"   # 585858
  SILVER = "\033[38;5;248m" # A8A8A8
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

def test_colors():
  """Print each color name rendered in its own color, next to its escape literal."""
  for name, code in vars(Color).items():
    if not name.isupper() or name == "END": continue
    literal = code.replace("\033", r"\033")
    print(f"{code}{name:8}{Color.END}{literal:15}")

if __name__ == "__main__":
  test_colors()
