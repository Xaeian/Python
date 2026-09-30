# tests/test_colors.py

"""ANSI color codes and pre-formatted level indicators."""

from xaeian import Color, Ico

def color_codes_are_ansi_escape_sequences():
  assert Color.RED.startswith("\033[") and Color.RED.endswith("m")
  assert Color.END == "\033[0m"

def ico_wraps_label_in_color_and_reset():
  assert Ico.ERR == f"{Color.RED}ERR{Color.END}"
  assert Ico.INF == f"{Color.BLUE}INF{Color.END}"
  assert Ico.OK == f"{Color.GREEN}OK{Color.END}"

def ico_gap_is_blank_padding():
  assert Ico.GAP == "   " and Ico.GAP.strip() == ""
