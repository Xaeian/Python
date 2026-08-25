# tests/test_eda_kicad.py

"""
KiCad helpers without `kicad-cli`: the pure functions, and the instance over a bare board.

The exports themselves need the real CLI and a real project; what is testable hermetically
is the BOM/CPL arithmetic - filtering, merging, selector matching - and the class's contract:
it narrates through its own `log` and raises instead of ending the host process.
"""

import io
import pytest

pytest.importorskip("sexpdata", reason="eda needs the [eda] extra")

from xaeian.eda import kicad
from xaeian.log import Print

#----------------------------------------------------------------------------------- pure functions

def expand_flattens_tuple_keys():
  assert kicad._expand({("A", "B"): 90, "C": 180.0}) == {"A": 90.0, "B": 90.0, "C": 180.0}

def filter_dnp_trims_refs_and_recounts():
  rows = [{"Reference": "R1,R2,R3", "Count": 3}, {"Reference": "C1", "Count": 1}]
  out = kicad._filter_dnp(rows, ["R2"])
  assert out[0]["Reference"] == "R1,R3" and out[0]["Count"] == 2
  assert out[1]["Reference"] == "C1"

def filter_dnp_drops_a_row_left_empty():
  assert kicad._filter_dnp([{"Reference": "R1", "Count": 1}], ["R1"]) == []

def merge_rows_joins_rows_sharing_manufacturer_and_code():
  merged = kicad._merge_rows([
    {"Manufacturer": "TI", "Code": "X", "Count": 1, "Reference": "U1"},
    {"Manufacturer": "TI", "Code": "X", "Count": 2, "Reference": "U2"},
    {"Manufacturer": "TI", "Code": "Y", "Count": 1, "Reference": "U3"},
  ])
  assert merged[0]["Count"] == 3 and merged[0]["Reference"] == "U1,U2"
  assert len(merged) == 2

def as_names_flattens_and_rejects_non_strings():
  assert kicad._as_names(["a", ("b", ["c"])], "x") == ["a", "b", "c"]
  with pytest.raises(TypeError):
    kicad._as_names(42, "x")

def pkg_match_prefers_exact_over_substring():
  rows = [{"Package": "Lib:SOT23-3"}, {"Package": "SOT23-3W"}]
  assert kicad._pkg_match("sot23-3", rows) == [{"Package": "Lib:SOT23-3"}]
  assert len(kicad._pkg_match("sot23", rows)) == 2

def load_netlist_reads_components_and_the_dnp_property(tmp_path):
  net = tmp_path / "board.net"
  net.write_text("""(export (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "R:0603")
      (property (name "Code") (value "RC0603FR-0710KL")))
    (comp (ref "R2") (value "10k") (footprint "R:0603")
      (property (name "dnp")))))""", encoding="utf-8")
  rows = kicad.load_netlist(str(net))
  assert [r["Reference"] for r in rows] == ["R1", "R2"]
  assert rows[0]["Code"] == "RC0603FR-0710KL" and rows[0]["DNP"] is False
  assert rows[1]["DNP"] is True

#----------------------------------------------------------------------------------------- instance

@pytest.fixture
def board(tmp_path):
  """A project holding one empty `.kicad_pcb`: enough for the class, nothing for the CLI."""
  (tmp_path / "board.kicad_pcb").touch()
  buf = io.StringIO()
  kc = kicad.KiCad(str(tmp_path), str(tmp_path / "produce"), log=Print(file=buf))
  return kc, buf

def the_project_is_recognised_without_a_schematic(board):
  kc, _ = board
  assert kc.name == "board" and kc.has_pcb and not kc.has_sch

def a_selector_that_hits_nothing_warns_and_contributes_nothing(board):
  kc, buf = board
  assert kc._match_refs(["R*", "C9"], {"R1", "R2"}, "DNP") == ["R1", "R2"]
  assert "no ref matches 'C9'" in buf.getvalue()

def a_failed_cli_call_raises_instead_of_exiting(board, monkeypatch):
  kc, buf = board
  class Failed:
    returncode = 1
    stderr = "boom\n"
    stdout = ""
  monkeypatch.setattr(kicad, "cmd_run", lambda args: Failed())
  with pytest.raises(RuntimeError, match="kicad-cli failed"):
    kc._execute(["kicad-cli", "pcb", "export"])
  assert "boom" in buf.getvalue()

#------------------------------------------------------------------------------ rotation by package

def a_package_rotation_that_matches_nothing_warns_through_the_log(board):
  """A `@staticmethod` still reaching for `self.log`: every miss raised NameError."""
  kc, buf = board
  rows = [{"Ref": "U1", "Package": "SOT23"}]
  assert kc._rot_by_package(rows, {"NOSUCH": 90}) == {}
  assert "no footprint 'NOSUCH'" in buf.getvalue()
  assert kc._rot_by_package(rows, {"SOT23": 90}) == {"U1": 90.0}
