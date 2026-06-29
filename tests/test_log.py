# tests/test_log.py

"""Colored logging: Print (level-filtered output) and Logger (rotating file)."""

import io
import logging
from xaeian import logger, Print

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
  p.inf("hi"); p.dot("under-inf")   # INFO < WRN → both suppressed
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

def print_long_aliases_delegate_to_short():
  buf = io.StringIO()
  p = Print(file=buf, level="WRN")
  p.info("hidden"); p.error("visible")
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

def logger_item_inherits_last_level(tmp_path):
  log = logger("xaeian_test_b", file=str(tmp_path / "b.log"), stream=False, file_lvl=logging.DEBUG)
  log.error("failed")
  log.item("detail") # " -  " prefix, logged at the last level (ERROR)
  assert "ERR  -  detail" in (tmp_path / "b.log").read_text(encoding="utf-8")

def logger_ok_appends_stripped_badge(tmp_path):
  log = logger("xaeian_test_c", file=str(tmp_path / "c.log"), stream=False, file_lvl=logging.DEBUG)
  log.ok("done")
  assert "INF done OK" in (tmp_path / "c.log").read_text(encoding="utf-8")

def logger_respects_file_level(tmp_path):
  log = logger("xaeian_test_d", file=str(tmp_path / "d.log"), stream=False, file_lvl=logging.WARNING)
  log.info("below"); log.warning("at")
  content = (tmp_path / "d.log").read_text(encoding="utf-8")
  assert "below" not in content and "WRN at" in content

def logger_file_property_reports_path(tmp_path):
  path = str(tmp_path / "e.log")
  log = logger("xaeian_test_e", file=path, stream=False)
  assert log.file == path
