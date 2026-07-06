# tests/test_files_json_smart.py

"""JSON.smart layout: inline/multiline decisions for arrays, matrices and dicts.

Round-trips for INI/JSON/YAML/CSV live in test_files.py; this file only pins
the smart formatter's layout, which is the part most likely to regress.
"""

import json

import pytest
from xaeian.files.json import JSON

#---------------------------------------------------------------------- layout stays valid JSON

@pytest.mark.parametrize("data", [
  [1, 2, 3],
  list(range(50)),
  [[1, 2, 3], [4, 5, 6]],
  {"a": 1, "b": 2, "c": 3},
  {"outer": {"k": list(range(20))}},
  [{"a": 1}, {"b": 2}],
  [], {},
])
def smart_output_is_always_valid_json(data):
  # however smart lays it out, it must still parse back to the original value
  assert json.loads(JSON.smart(data)) == data

#------------------------------------------------------------------------------- numeric arrays

def short_numeric_array_stays_inline():
  assert JSON.smart([1, 2, 3]) == "[1, 2, 3]"

def long_numeric_array_wraps_into_chunks():
  assert JSON.smart(list(range(7)), array_wrap=3, max_line=10) == (
    "[\n"
    "  0, 1, 2,\n"
    "  3, 4, 5,\n"
    "  6\n"
    "]"
  )

#---------------------------------------------------------------------------- 2D numeric matrix

def matrix_puts_each_row_on_its_own_line():
  assert JSON.smart([[1, 2, 3], [4, 5, 6]], max_line=5, array_wrap=3) == (
    "[\n"
    "  [ 1, 2, 3 ],\n"
    "  [ 4, 5, 6 ]\n"
    "]"
  )

def matrix_row_wraps_when_too_long():
  assert JSON.smart([[1, 2, 3, 4, 5]], max_line=6, array_wrap=2) == (
    "[\n"
    "  [ 1, 2,\n"
    "    3, 4,\n"
    "    5 ]\n"
    "]"
  )

#--------------------------------------------------------------------------------- dictionaries

def flat_dict_packs_entries_up_to_the_line_width():
  assert JSON.smart({"a": 1, "b": 2, "c": 3, "d": 4}, max_line=24) == (
    "{\n"
    '  "a": 1, "b": 2, "c": 3,\n'
    '  "d": 4\n'
    "}"
  )

def nested_dict_expands_to_multiline():
  # range(11) == 0..10; default array_wrap is 10, so the 11th value spills to a new line
  assert JSON.smart({"outer": {"k": list(range(11))}}, max_line=10) == (
    "{\n"
    '  "outer": {\n'
    '    "k": [\n'
    "      0, 1, 2, 3, 4, 5, 6, 7, 8, 9,\n"
    "      10\n"
    "    ]\n"
    "  }\n"
    "}"
  )

#----------------------------------------------------------------------------------- containers

def list_of_objects_breaks_onto_multiple_lines():
  assert JSON.smart([{"a": 1}, {"b": 2}], max_line=5) == (
    "[\n"
    "  {\n"
    '    "a": 1\n'
    "  },\n"
    "  {\n"
    '    "b": 2\n'
    "  }\n"
    "]"
  )

def empty_containers_render_compact():
  assert JSON.smart([]) == "[]"
  assert JSON.smart({}) == "{}"
