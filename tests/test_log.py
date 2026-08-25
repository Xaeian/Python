# tests/test_log.py

"""Colored logging: Print (level-filtered output) and Logger (rotating file)."""

import io
import logging
from xaeian import logger, Print, Color

# Print writes to its `file=`; assertions use substrings (the level marker text
# is embedded in the colored Ico, so it survives regardless of ANSI codes).

def print_filters_below_threshold():
  buf = io.StringIO()
  p = Print(file=buf, level="WRN")
  p.inf("ignored")
  p.err("shown")
  out = buf.getvalue()
  assert "ignored" not in out
  assert "shown" in out and "ERR" in out

def print_default_level_shows_debug():
  buf = io.StringIO()
  Print(file=buf).dbg("hello")
  assert "hello" in buf.getvalue()

def print_sub_entry_inherits_last_level():
  buf = io.StringIO()
  p = Print(file=buf, level="WRN")
  p.inf("hi"); p.dot("under-inf") # INFO < WRN → both suppressed
  p.err("boom"); p.dot("under-err") # ERROR shown; dot inherits ERROR → shown
  out = buf.getvalue()
  assert "under-inf" not in out
  assert "boom" in out and "under-err" in out

def print_level_property_accepts_name_or_int():
  p = Print()
  p.level = "WRN"
  assert p.level == logging.WARNING
  p.level = 10
  assert p.level == 10

def print_speaks_the_shared_vocabulary():
  buf = io.StringIO()
  p = Print(file=buf, level="WRN")
  p.inf("hidden"); p.err("visible")
  out = buf.getvalue()
  assert "hidden" not in out and "visible" in out

def print_ok_appends_badge():
  buf = io.StringIO()
  Print(file=buf).ok("done") # INFO ≥ default DBG → shown
  out = buf.getvalue()
  assert "done" in out and "OK" in out

# Logger's file handler writes plain, ANSI-stripped lines with 3-char levels.

def logger_writes_abbreviated_levels_to_file(tmp_path):
  log = logger("xaeian_test_a", file=str(tmp_path / "a.log"), stream=False, file_lvl=logging.DEBUG)
  log.debug("dbgmsg"); log.error("boom"); log.warning("warn"); log.panic("kaboom")
  content = (tmp_path / "a.log").read_text(encoding="utf-8")
  for line in ("DBG dbgmsg", "ERR boom", "WRN warn", "PNC kaboom"):
    assert line in content

def logger_strips_ansi_from_lazy_percent_args(tmp_path):
  log = logger("xaeian_test_ansi", file=str(tmp_path / "f.log"), stream=False,
    file_lvl=logging.DEBUG)
  log.error("fail %s", f"{Color.RED}x{Color.END}")
  content = (tmp_path / "f.log").read_text(encoding="utf-8")
  assert "\x1b" not in content and "ERR fail x" in content

def logger_dot_inherits_last_level(tmp_path):
  log = logger("xaeian_test_b", file=str(tmp_path / "b.log"), stream=False, file_lvl=logging.DEBUG)
  log.error("failed")
  log.dot("detail") # " -  " prefix, logged at the last level (ERROR)
  assert "ERR  -  detail" in (tmp_path / "b.log").read_text(encoding="utf-8")

def logger_ok_appends_stripped_badge(tmp_path):
  log = logger("xaeian_test_c", file=str(tmp_path / "c.log"), stream=False, file_lvl=logging.DEBUG)
  log.ok("done")
  assert "INF done OK" in (tmp_path / "c.log").read_text(encoding="utf-8")

def logger_respects_file_level(tmp_path):
  log = logger("xaeian_test_d", file=str(tmp_path / "d.log"), stream=False,
    file_lvl=logging.WARNING)
  log.info("below"); log.warning("at")
  content = (tmp_path / "d.log").read_text(encoding="utf-8")
  assert "below" not in content and "WRN at" in content

def logger_file_property_reports_path(tmp_path):
  path = str(tmp_path / "e.log")
  log = logger("xaeian_test_e", file=path, stream=False)
  assert log.file == path

def console_level_tags_come_from_ico():
  from xaeian import Ico
  from xaeian.log import ColorFormatter
  for short, tag in ColorFormatter.TAGS.items():
    assert tag == getattr(Ico, short)

# The contract `log=` relies on: anything the library calls on an injected logger must exist
# on both classes with the same name.
CONTRACT = ["dbg", "inf", "wrn", "err", "crt", "pnc", "tip", "run", "ok", "gap", "dot"]

def print_and_logger_answer_one_vocabulary():
  log = logger("xaeian_test_contract", file=False, stream=False)
  p = Print(file=io.StringIO())
  for name in CONTRACT:
    assert callable(getattr(p, name, None)), f"Print has no {name}()"
    assert callable(getattr(log, name, None)), f"Logger has no {name}()"

def print_does_not_carry_stdlib_aliases():
  p = Print(file=io.StringIO())
  for name in ("debug", "info", "warning", "error", "critical", "panic", "item", "space"):
    assert not hasattr(p, name), f"Print still carries the {name}() alias"
