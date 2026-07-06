# tests/test_db_utils.py

"""DB serialization and SQL builders: pure string/param generation, no live database."""

from datetime import datetime, timezone

import pytest
from xaeian.db.utils import (
  serialize, norm, serialize_params, serialize_dict, listify,
  ident, ph, ph_list, renum_ph,
  _insert_sql, _insert_many_sql, _update_sql, _find_sql, _upsert_sql,
  parse_json, parse_row, to_dicts, split_sql,
)

#------------------------------------------------------------------------------------ serialize

def serialize_turns_containers_into_json():
  assert serialize({"k": "v"}) == '{"k": "v"}'
  assert serialize([1, 2, 3]) == "[1, 2, 3]"

def serialize_parses_iso_datetime():
  expected = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
  assert serialize("2024-01-15T10:30:00Z") == expected

def serialize_leaves_plain_values_untouched():
  assert serialize("hello") == "hello"
  assert serialize(42) == 42
  assert serialize(None) is None

def serialize_keeps_invalid_iso_as_string():
  # matches the ISO shape but is not a real date → fromisoformat fails, string survives
  assert serialize("2024-13-99") == "2024-13-99"

#----------------------------------------------------------------------------------------- norm

@pytest.mark.parametrize("raw, expected", [
  (None, ()),
  (42, (42,)),
  ([1, 2, 3], (1, 2, 3)),
  ((1, 2), (1, 2)),
])
def norm_coerces_to_tuple(raw, expected):
  assert norm(raw) == expected

def serialize_params_normalizes_then_serializes():
  assert serialize_params([{"a": 1}, "plain"]) == ('{"a": 1}', "plain")

def serialize_dict_serializes_each_value():
  assert serialize_dict({"meta": {"a": 1}, "name": "x"}) == {"meta": '{"a": 1}', "name": "x"}

#-------------------------------------------------------------------------------------- listify

def listify_converts_tuples_recursively():
  assert listify((1, (2, 3), [4, (5,)])) == [1, [2, 3], [4, [5]]]

def listify_passes_scalars_through():
  assert listify("x") == "x"

#---------------------------------------------------------------------------------------- ident

@pytest.mark.parametrize("name", ["users", "user_id", "_private", "t1"])
def ident_accepts_valid_identifiers(name):
  assert ident(name) == name

@pytest.mark.parametrize("name", ["drop table", "a;b", "col-name", "a.b", ""])
def ident_rejects_dangerous_names(name):
  with pytest.raises(ValueError):
    ident(name)

#---------------------------------------------------------------------------- placeholders (ph)

def ph_default_style():
  assert ph(3) == "(?, ?, ?)"

def ph_postgres_style_is_numbered():
  assert ph(3, "$") == "($1, $2, $3)"
  assert ph(2, "$", offset=3) == "($4, $5)" # continue after 3 earlier params

def ph_mysql_percent_style():
  assert ph(2, "%s") == "(%s, %s)"

def ph_list_mirrors_ph_without_parens():
  assert ph_list(3) == ["?", "?", "?"]
  assert ph_list(3, "$") == ["$1", "$2", "$3"]
  assert ph_list(2, "$", offset=2) == ["$3", "$4"]

#------------------------------------------------------------------------------------- renum_ph

def renum_ph_shifts_numbered_placeholders():
  assert renum_ph("id = $1 AND status = $2", 3) == "id = $4 AND status = $5"

def renum_ph_is_noop_for_zero_offset():
  assert renum_ph("id = $1", 0) == "id = $1"

def renum_ph_ignores_clauses_without_placeholders():
  assert renum_ph("deleted = 0", 5) == "deleted = 0"

#---------------------------------------------------------------------------------- SQL: INSERT

def insert_builds_columns_and_placeholders():
  sql, params = _insert_sql("users", {"name": "bob", "age": 30}, "?")
  assert sql == "INSERT INTO users (name, age) VALUES (?, ?)"
  assert params == ("bob", 30)

def insert_serializes_container_values():
  sql, params = _insert_sql("events", {"payload": {"x": 1}}, "$")
  assert sql == "INSERT INTO events (payload) VALUES ($1)"
  assert params == ('{"x": 1}',)

def insert_many_shares_one_statement_with_per_row_params():
  sql, rows = _insert_many_sql("t", [{"a": 1}, {"a": 2}], "%s")
  assert sql == "INSERT INTO t (a) VALUES (%s)"
  assert rows == [(1,), (2,)]

#---------------------------------------------------------------------------------- SQL: UPDATE

def update_renumbers_where_after_set_params():
  # SET takes $1; the caller's WHERE "$1" must shift to "$2"
  sql, params = _update_sql("users", {"name": "x"}, "id = $1", [5], "$")
  assert sql == "UPDATE users SET name = $1 WHERE id = $2"
  assert params == ("x", 5)

#---------------------------------------------------------------------------------- SQL: UPSERT

def upsert_sqlite_dialect():
  sql, params = _upsert_sql("t", {"id": 1, "name": "a"}, "id", None, "?", "excluded")
  assert sql == ("INSERT INTO t (id, name) VALUES (?, ?)"
                 " ON CONFLICT (id) DO UPDATE SET name = excluded.name")
  assert params == (1, "a")

def upsert_postgres_dialects():
  sql, _ = _upsert_sql("t", {"id": 1, "name": "a"}, "id", None, "%s", "EXCLUDED")
  assert sql == ("INSERT INTO t (id, name) VALUES (%s, %s)"
                 " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name")
  sql, _ = _upsert_sql("t", {"id": 1, "name": "a"}, "id", None, "$", "EXCLUDED")
  assert sql == ("INSERT INTO t (id, name) VALUES ($1, $2)"
                 " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name")

def upsert_mysql_dialect_has_no_conflict_clause():
  sql, _ = _upsert_sql("t", {"id": 1, "name": "a"}, "id", None, "%s", None)
  assert sql == ("INSERT INTO t (id, name) VALUES (%s, %s)"
                 " ON DUPLICATE KEY UPDATE name = VALUES(name)")

def upsert_composite_key_and_explicit_update():
  sql, _ = _upsert_sql("t", {"a": 1, "b": 2, "c": 3}, ["a", "b"], None, "?", "excluded")
  assert "ON CONFLICT (a, b) DO UPDATE SET c = excluded.c" in sql
  sql, _ = _upsert_sql("t", {"a": 1, "b": 2, "c": 3}, "a", ["b"], "?", "excluded")
  assert sql.endswith("DO UPDATE SET b = excluded.b")

#------------------------------------------------------------------------------------ SQL: FIND

def find_plain_select_without_clauses():
  assert _find_sql("t", None, None, "?", {}) == ("SELECT * FROM t", ())

def find_assembles_where_order_and_limit():
  sql, params = _find_sql("users", "id DESC", 10, "?", {"active": True})
  assert sql == "SELECT * FROM users WHERE active = ? ORDER BY id DESC LIMIT 10"
  assert params == (True,)

#----------------------------------------------------------------------------------- parse_json

def parse_json_decodes_valid_json():
  assert parse_json('{"key": "value"}') == {"key": "value"}

def parse_json_returns_original_on_garbage():
  assert parse_json("not json") == "not json"
  assert parse_json(None) is None
  assert parse_json({"already": "parsed"}) == {"already": "parsed"}
  assert parse_json(42) == 42 # non-string, non-container passes straight through

def parse_row_only_decodes_marked_columns():
  assert parse_row(["a", '{"x": 1}', "{not json}"], {1}) == ["a", {"x": 1}, "{not json}"]

#------------------------------------------------------------------------------------- to_dicts

def to_dicts_zips_columns_to_values():
  assert to_dicts([(1, "a"), (2, "b")], ["id", "name"]) == [
    {"id": 1, "name": "a"}, {"id": 2, "name": "b"},
  ]

def to_dicts_parses_named_json_columns():
  rows = to_dicts([(1, '{"x": 1}')], ["id", "meta"], json=["meta"])
  assert rows == [{"id": 1, "meta": {"x": 1}}]

#------------------------------------------------------------------------------------ split_sql

def split_sql_keeps_statements_separate():
  assert split_sql("SELECT 1; SELECT 2") == ["SELECT 1;", "SELECT 2;"]

def split_sql_respects_semicolons_inside_quotes():
  assert split_sql("SELECT 'a;b'") == ["SELECT 'a;b';"]
