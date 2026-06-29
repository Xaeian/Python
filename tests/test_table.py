# tests/test_table.py

"""Tabular ops on list[dict]: filter, columns, sort/dedup, group/aggregate, join, markdown."""

import pytest
from xaeian.table import (
  where, first, take,
  columns, select, exclude, rename, add_column, pluck, set_defaults,
  sort_by, unique,
  group_by, count_by, aggregate,
  join, concat,
  replace_values, map_column,
  describe, markdown, markdown_raw,
)

@pytest.fixture
def rows():
  return [
    {"name": "Ann", "dept": "eng", "salary": 100},
    {"name": "Bob", "dept": "eng", "salary": 120},
    {"name": "Cy", "dept": "ops", "salary": 90},
  ]

def where_filters_by_predicate(rows):
  assert where(rows, lambda r: r["salary"] >= 100) == rows[:2]

def first_returns_match_or_none(rows):
  assert first(rows, lambda r: r["dept"] == "ops") == rows[2]
  assert first(rows, lambda r: r["dept"] == "hr") is None

def take_slices_with_offset(rows):
  assert take(rows, 1, offset=1) == [rows[1]]

def columns_from_first_row(rows):
  assert columns(rows) == ["name", "dept", "salary"]
  assert columns([]) == []

def select_keeps_only_named_columns(rows):
  assert select(rows, "name") == [{"name": "Ann"}, {"name": "Bob"}, {"name": "Cy"}]

def exclude_drops_named_columns(rows):
  assert exclude(rows, "salary", "dept") == [{"name": "Ann"}, {"name": "Bob"}, {"name": "Cy"}]

def rename_remaps_keys(rows):
  assert rename(rows, {"dept": "team"})[0] == {"name": "Ann", "team": "eng", "salary": 100}

def add_column_computes_in_place(rows):
  out = add_column(rows, "bonus", lambda r: r["salary"] // 10)
  assert out is rows and rows[0]["bonus"] == 10 # mutates and returns the same list

def pluck_extracts_one_column(rows):
  assert pluck(rows, "name") == ["Ann", "Bob", "Cy"]

def set_defaults_fills_only_missing():
  data = [{"a": 1}, {"a": 2, "b": 9}]
  set_defaults(data, b=0)
  assert data == [{"a": 1, "b": 0}, {"a": 2, "b": 9}] # existing b kept

def sort_by_orders_with_none_last():
  data = [{"s": 3}, {"s": None}, {"s": 1}]
  assert pluck(sort_by(data, "s"), "s") == [1, 3, None]
  assert pluck(sort_by(data, "s", reverse=True), "s") == [3, 1, None]

def sort_by_tolerates_mixed_types():
  assert pluck(sort_by([{"x": 1}, {"x": "a"}, {"x": 2}], "x"), "x") == [1, 2, "a"]

def unique_dedupes_by_key_and_unhashable():
  assert unique([{"id": 1}, {"id": 1}, {"id": 2}], "id") == [{"id": 1}, {"id": 2}]
  assert unique([{"t": [1, 2]}, {"t": [1, 2]}, {"t": [3]}], "t") == [{"t": [1, 2]}, {"t": [3]}]

def group_by_buckets_rows(rows):
  groups = group_by(rows, "dept")
  assert list(groups) == ["eng", "ops"] and len(groups["eng"]) == 2

def count_by_counts_values(rows):
  assert count_by(rows, "dept") == {"eng": 2, "ops": 1}

def aggregate_supports_sum_count_join(rows):
  assert aggregate(rows, "dept", {"salary": "sum", "name": "join", "n": "count"}) == [
    {"dept": "eng", "salary": 220, "name": "Ann,Bob", "n": 2},
    {"dept": "ops", "salary": 90, "name": "Cy", "n": 1},
  ]
  assert aggregate(rows, "dept", {"name": "join:;"})[0]["name"] == "Ann;Bob"

@pytest.mark.parametrize("agg, eng_value", [
  ("mean", 110.0), ("min", 100), ("max", 120),
  ("first", 100), ("last", 120),
  (lambda vs: sum(vs), 220),
])
def aggregate_reduces_eng_salary(rows, agg, eng_value):
  assert aggregate(rows, "dept", {"salary": agg})[0]["salary"] == eng_value

@pytest.mark.parametrize("how, names", [
  ("inner", ["a"]),
  ("left", ["a", "b"]),
  ("right", ["a", None]),
  ("outer", ["a", "b", None]),
])
def join_modes_match_keys(how, names):
  left = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
  right = [{"id": 1, "city": "X"}, {"id": 3, "city": "Z"}]
  assert pluck(join(left, right, on="id", how=how), "name") == names

def concat_stacks_and_fills_missing():
  assert concat([{"a": 1}], [{"b": 2}]) == [{"a": 1, "b": None}, {"a": None, "b": 2}]

def replace_values_maps_in_place(rows):
  replace_values(rows, "dept", {"eng": "E"})
  assert pluck(rows, "dept") == ["E", "E", "ops"]

def map_column_applies_fn_in_place(rows):
  map_column(rows, "salary", lambda v: v + 1)
  assert pluck(rows, "salary") == [101, 121, 91]

def describe_summarizes_numeric_column(rows):
  d = describe(rows, "salary")
  assert (d["count"], d["nulls"], d["unique"], d["min"], d["max"]) == (3, 0, 3, 90, 120)
  assert d["mean"] == pytest.approx(103.333, abs=0.01)

def describe_counts_nulls_and_skips_non_numeric_mean():
  d = describe([{"v": "x"}, {"v": None}, {"v": "y"}], "v")
  assert (d["count"], d["nulls"], d["unique"], d["mean"]) == (3, 1, 2, None)

def markdown_renders_table_with_auto_align():
  data = [{"name": "R1", "value": 10}, {"name": "R2", "value": 22}]
  assert markdown(data) == (
    "| name | value |\n"
    "| :--- | ----: |\n" # numeric column auto-aligns right
    "| R1   |    10 |\n"
    "| R2   |    22 |"
  )

def markdown_raw_renders_list_of_lists():
  raw = [["Name", "Ohm"], ["R1", "10k"], ["R2", "22k"]]
  assert markdown_raw(raw) == (
    "| Name | Ohm |\n"
    "| :--- | :-- |\n"
    "| R1   | 10k |\n"
    "| R2   | 22k |"
  )

def markdown_escapes_pipe_and_handles_empty():
  assert markdown([{"a": "x|y"}]) == "| a    |\n| :--- |\n| x\\|y |"
  assert markdown([]) == ""
