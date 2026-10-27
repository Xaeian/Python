# tests/test_colors.py

"""ANSI color codes, pre-formatted level indicators and the look of a value."""

from xaeian import Color, Ico, grey, fmt_id, fmt_path, fmt_cmd, fmt_count, fmt_list

E = Color.END

def color_codes_are_ansi_escape_sequences():
  assert Color.RED.startswith("\033[") and Color.RED.endswith("m")
  assert Color.END == "\033[0m"

def ico_wraps_label_in_color_and_reset():
  assert Ico.ERR == f"{Color.RED}ERR{Color.END}"
  assert Ico.INF == f"{Color.BLUE}INF{Color.END}"
  assert Ico.OK == f"{Color.GREEN}OK{Color.END}"

def ico_gap_is_blank_padding():
  assert Ico.GAP == "   " and Ico.GAP.strip() == ""

def an_id_is_cream_and_pads_to_its_batch():
  assert fmt_id(42) == f"{Color.CREAM}#42{E}"
  assert fmt_id(3, 12) == f"{Color.CREAM}#3{E} "

def a_path_greys_its_folder_and_colours_its_name():
  assert fmt_path("out/img/a.svg") == f"{Color.GREY}out/img/{E}{Color.BLUE}a.svg{E}"
  assert fmt_path("a.svg", Color.SKY) == f"{Color.SKY}a.svg{E}"

def a_command_reads_as_a_console_shows_it():
  assert fmt_cmd("py -m draw.check <style>") == (f"{Color.YELLOW}py{E} {grey('-m')} "
    f"draw.check {grey('<style>')}")
  assert fmt_cmd("xn tree . | more").split(" ")[0] == f"{Color.GOLD}xn{E}"
  assert fmt_cmd("xn tree . | more").endswith(f"{grey('|')} {Color.YELLOW}more{E}")

def a_count_takes_the_word_for_its_number():
  assert fmt_count(1, "file") == f"{Color.BLUE}1{E} file"
  assert fmt_count(2, "entry", "entries", "") == "2 entries"

def a_list_colours_each_name():
  assert fmt_list(["a", "b"]) == f"{Color.SKY}a{E}, {Color.SKY}b{E}"
