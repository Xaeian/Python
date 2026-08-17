# tests/test_db_kv_common.py

"""KeyValue store internals: key/table validation, canonical JSON, SQL builders."""

import json
import time

import pytest
from xaeian.db.kv_common import (
  check_key, check_table, dumps, loads, now_ms,
  KEY_MAX, VALUE_MAX_BYTES,
  sql_create, sql_get_value, sql_get_meta, sql_read_all, sql_read_all_meta, where_key,
)

#------------------------------------------------------------------------------------ check_key

@pytest.mark.parametrize("key", ["a", "config.timeout", "x" * KEY_MAX])
def check_key_accepts_reasonable_keys(key):
  check_key(key) # no exception == pass

def check_key_rejects_non_string():
  with pytest.raises(TypeError):
    check_key(123)

def check_key_rejects_empty():
  with pytest.raises(ValueError):
    check_key("")

def check_key_rejects_overlong():
  with pytest.raises(ValueError):
    check_key("x" * (KEY_MAX + 1))

#---------------------------------------------------------------------------------- check_table

@pytest.mark.parametrize("table", ["kv", "_store", "Cache1"])
def check_table_accepts_valid_identifiers(table):
  check_table(table)

def check_table_rejects_non_string():
  with pytest.raises(TypeError):
    check_table(None)

@pytest.mark.parametrize("table", ["", "1table", "drop table", "a-b", "a;b"])
def check_table_rejects_bad_identifiers(table):
  # stricter than keys: table names are interpolated into DDL, so no leading digit / symbols
  with pytest.raises(ValueError):
    check_table(table)

def check_table_rejects_overlong():
  with pytest.raises(ValueError):
    check_table("t" * (KEY_MAX + 1))

#---------------------------------------------------------------------------------------- dumps

def dumps_is_canonical_sorted_and_compact():
  assert dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}'

def dumps_preserves_unicode():
  text = dumps("zażółć")
  assert "\\u" not in text # not escaped
  assert json.loads(text) == "zażółć"

def dumps_rejects_oversized_values():
  with pytest.raises(ValueError):
    dumps("x" * (VALUE_MAX_BYTES + 1))

def dumps_rejects_non_json_types():
  with pytest.raises(TypeError):
    dumps({1, 2, 3}) # a set is not JSON-serializable

#---------------------------------------------------------------------------------------- loads

def loads_round_trips_dumps():
  for value in [None, True, 42, 1.5, "text", [1, 2], {"a": 1}]:
    assert loads(dumps(value), "k") == value

def loads_rejects_non_string_row():
  with pytest.raises(ValueError):
    loads(123, "mykey")

def loads_wraps_bad_json_with_key_context():
  with pytest.raises(ValueError, match="mykey"):
    loads("{not json}", "mykey")

#--------------------------------------------------------------------------------------- now_ms

def now_ms_returns_epoch_milliseconds():
  ts = now_ms()
  assert isinstance(ts, int)
  # bracket against the wall clock: catches a seconds (too small) or nanoseconds mixup
  assert time.time() * 1000 - 5000 < ts < time.time() * 1000 + 5000

#--------------------------------------------------------------------------------- SQL builders

def sql_create_declares_kv_schema():
  assert sql_create("kv") == (
    "CREATE TABLE IF NOT EXISTS kv ("
    f"key VARCHAR({KEY_MAX}) PRIMARY KEY, "
    "value TEXT NOT NULL, "
    "updated_at BIGINT NOT NULL)"
  )

def sql_get_value_selects_single_value():
  assert sql_get_value("kv", "?") == "SELECT value FROM kv WHERE key = ?"

def sql_get_meta_selects_value_and_timestamp():
  assert sql_get_meta("kv", "$1") == "SELECT value, updated_at FROM kv WHERE key = $1"

def sql_read_all_is_ordered_by_key():
  assert sql_read_all("kv") == "SELECT key, value FROM kv ORDER BY key"

def sql_read_all_meta_includes_timestamp():
  assert sql_read_all_meta("kv") == "SELECT key, value, updated_at FROM kv ORDER BY key"

def where_key_builds_lookup_clause():
  assert where_key("%s") == "key = %s"

@pytest.mark.parametrize("build", [
  lambda t: sql_create(t),
  lambda t: sql_get_value(t, "?"),
  lambda t: sql_get_meta(t, "?"),
  lambda t: sql_read_all(t),
  lambda t: sql_read_all_meta(t),
], ids=["create", "get_value", "get_meta", "read_all", "read_all_meta"])
def sql_builders_reject_bad_table_names(build):
  # every table name flows through ident(), so injection attempts blow up at build time
  with pytest.raises(ValueError):
    build("kv; DROP TABLE kv")
