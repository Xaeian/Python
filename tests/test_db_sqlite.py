# tests/test_db_sqlite.py

"""SQLite end-to-end: drives AbstractDatabase + SqliteDatabase + KeyValue against a
real on-disk database. No server needed - this is the only backend testable in isolation.

A file under tmp_path (not ":memory:") is used on purpose: each operation opens a fresh
connection, so an in-memory db would be wiped between calls outside a transaction.
"""

import pytest
from xaeian.db import Database, KeyValue, DatabaseError

@pytest.fixture
def db(tmp_path):
  database = Database("sqlite", str(tmp_path / "app.db"))
  database.exec(
    "CREATE TABLE users ("
    "id INTEGER PRIMARY KEY, name TEXT, active INTEGER, meta TEXT)"
  )
  return database

#-------------------------------------------------------------------------------------- execute

def ping_succeeds_on_live_db(db):
  assert db.ping() is True

def exec_reports_affected_row_count(db):
  assert db.exec("INSERT INTO users (name) VALUES (?)", "Jan") == 1

def bad_sql_raises_database_error(db):
  with pytest.raises(DatabaseError):
    db.get_value("SELECT * FROM does_not_exist")

#----------------------------------------------------------------------------------------- CRUD

def insert_returning_gives_back_the_new_id(db):
  assert db.insert("users", {"name": "Jan"}, returning="id") == 1

def insert_many_then_count_and_exists(db):
  db.insert_many("users", [{"name": "Ada"}, {"name": "Bo"}, {"name": "Cy"}])
  assert db.count("users") == 3
  assert db.exists("users", "name = ?", "Ada") is True
  assert db.exists("users", "name = ?", "Zoe") is False

def update_and_delete_return_affected_rows(db):
  db.insert_many("users", [{"name": "a", "active": 0}, {"name": "b", "active": 0}])
  assert db.update("users", {"active": 1}, "active = ?", 0) == 2
  assert db.delete("users", "active = ?", 1) == 2
  assert db.count("users") == 0

#-------------------------------------------------------------------------------- query builder

def find_filters_orders_and_limits(db):
  db.insert_many("users", [
    {"name": "Ada", "active": 1}, {"name": "Bo", "active": 0}, {"name": "Cy", "active": 1},
  ])
  active = db.find("users", active=True, order="name")
  assert [u["name"] for u in active] == ["Ada", "Cy"]
  assert db.find_one("users", name="Bo")["active"] == 0
  assert len(db.find("users", limit=1)) == 1

def find_one_returns_none_when_no_match(db):
  assert db.find_one("users", name="ghost") is None

def paginate_splits_results_into_pages(db):
  db.insert_many("users", [{"name": f"u{i}"} for i in range(5)])
  page = db.paginate("SELECT * FROM users", page=1, per_page=2)
  assert page["total"] == 5
  assert page["pages"] == 3
  assert len(page["items"]) == 2

#------------------------------------------------------------------------------- automatic JSON

def dict_value_is_stored_as_json_and_parsed_back(db):
  db.insert("users", {"name": "Jan", "meta": {"role": "admin", "tags": [1, 2]}})
  # stored as canonical JSON text...
  stored = db.get_value("SELECT meta FROM users WHERE name = ?", "Jan")
  assert stored == '{"role": "admin", "tags": [1, 2]}'
  # ...and revived to a real dict when the column is marked json
  revived = db.find_one("users", json=["meta"], name="Jan")["meta"]
  assert revived == {"role": "admin", "tags": [1, 2]}

#--------------------------------------------------------------------------------- transactions

def transaction_commits_on_success(db):
  with db.transaction():
    db.insert("users", {"name": "Jan"})
    db.insert("users", {"name": "Ada"})
  assert db.count("users") == 2

def transaction_rolls_back_on_exception(db):
  db.insert("users", {"name": "keep"})
  with pytest.raises(RuntimeError):
    with db.transaction():
      db.insert("users", {"name": "discard"})
      raise RuntimeError("boom")
  assert db.count("users") == 1 # the in-transaction insert was rolled back

def nested_transaction_is_rejected(db):
  with db.transaction():
    with pytest.raises(RuntimeError):
      with db.transaction():
        pass

#--------------------------------------------------------------------------------------- upsert

def upsert_inserts_then_updates_on_conflict(db):
  db.exec("CREATE TABLE kv (k TEXT PRIMARY KEY, v INTEGER)")
  db.upsert("kv", {"k": "hits", "v": 1}, on="k")
  db.upsert("kv", {"k": "hits", "v": 99}, on="k") # same key → update, not a second row
  assert db.count("kv") == 1
  assert db.get_value("SELECT v FROM kv WHERE k = ?", "hits") == 99

#------------------------------------------------------------------------------- batch & schema

def exec_batch_runs_a_semicolon_string(db):
  rows = db.exec_batch(
    "INSERT INTO users (name) VALUES ('a'); INSERT INTO users (name) VALUES ('b')"
  )
  assert rows == 2
  assert db.count("users") == 2

def exec_batch_runs_a_list_of_sql_with_params(db):
  rows = db.exec_batch([
    ("INSERT INTO users (name) VALUES (?)", "a"),
    ("INSERT INTO users (name) VALUES (?)", "b"),
  ])
  assert rows == 2

def exec_batch_runs_a_list_of_plain_statements(db):
  rows = db.exec_batch([
    "INSERT INTO users (name) VALUES ('a')",
    "INSERT INTO users (name) VALUES ('b')",
  ])
  assert rows == 2

def schema_introspection_and_drop(db):
  assert db.has_table("users") is True
  assert "users" in db.tables()
  db.drop_table("users")
  assert db.has_table("users") is False

def drop_table_accepts_several_names(db):
  db.exec("CREATE TABLE a (x)")
  db.exec("CREATE TABLE b (x)")
  db.drop_table("users", "a", "b")
  assert db.tables() == []

def repr_and_transaction_flag(db):
  assert "SqliteDatabase" in repr(db)
  assert db.in_transaction() is False
  with db.transaction():
    assert db.in_transaction() is True

#--------------------------------------------------------------------------- database file mgmt

def database_file_create_and_drop(tmp_path):
  db = Database("sqlite", str(tmp_path / "fresh.db"))
  assert db.has_database() is False
  assert db.create_database() is True
  assert db.has_database() is True
  assert db.create_database() is False # already there
  assert db.drop_database() is True
  assert db.drop_database() is False  # already gone

#------------------------------------------------------------------------------- KeyValue store

@pytest.fixture
def kv(db):
  return KeyValue(db, table="cfg")

def kv_round_trips_json_values(kv):
  kv.set("flag", True)
  kv.set("limits", {"max": 100, "min": 1})
  kv.set("tags", ["a", "b"])
  assert kv.get("flag") is True
  assert kv.get("limits") == {"max": 100, "min": 1}
  assert kv.get("tags") == ["a", "b"]

def kv_creates_its_table_lazily(db, kv):
  assert db.has_table("cfg") is False # nothing written yet
  kv.set("x", 1)
  assert db.has_table("cfg") is True

def kv_distinguishes_stored_none_from_missing(kv):
  kv.set("nothing", None)
  assert kv.has("nothing") is True and kv.get("nothing") is None
  assert kv.has("missing") is False and kv.get("missing", "default") == "default"

def kv_meta_carries_an_integer_timestamp(kv):
  kv.set("x", 42)
  meta = kv.meta("x")
  assert meta["value"] == 42
  assert isinstance(meta["updated_at"], int)

def kv_set_overwrites_and_delete_removes(kv):
  kv.set("x", 1)
  kv.set("x", 2) # overwrite, not duplicate
  assert kv.get("x") == 2
  assert kv.delete("x") is True
  assert kv.has("x") is False
  assert kv.delete("x") is False # already gone

def kv_read_all_returns_whole_table(kv):
  kv.set("a", 1)
  kv.set("b", {"nested": True})
  assert kv.read_all() == {"a": 1, "b": {"nested": True}}

def kv_read_all_meta_includes_timestamps(kv):
  kv.set("a", 1)
  kv.set("b", 2)
  meta = kv.read_all_meta()
  assert set(meta) == {"a", "b"}
  assert meta["a"]["value"] == 1
  assert all(isinstance(e["updated_at"], int) for e in meta.values())

def kv_rejects_invalid_keys(kv):
  with pytest.raises(ValueError):
    kv.get("")
  with pytest.raises(TypeError):
    kv.set(123, "v")
