# `xaeian.db`

Lightweight database abstraction. SQLite, MySQL, PostgreSQL: sync and async.

## Install

```sh
pip install xaeian[db] # sync: pymysql, psycopg2
pip install xaeian[db-async] # async: aiomysql, asyncpg, aiosqlite
```

## Quick Start

```py
from xaeian.db import Database, AsyncDatabase

db = Database("sqlite", "app.db")
db = Database("mysql", "mydb", user="root", password="secret")
db = Database("postgres", "mydb", user="postgres", password="secret")
# Async
db = AsyncDatabase("postgres", "mydb", user="postgres", password="secret")
```

## CRUD

```py
# Insert
db.insert("users", {"name": "Jan", "email": "jan@x.com"})  # returns row count
user_id = db.insert("users", {"name": "Jan"}, returning="id")  # returns new id
# Insert many
db.insert_many("users", [
  {"name": "Jan", "email": "jan@x.com"},
  {"name": "Anna", "email": "anna@x.com"},
])
# Select
users = db.get_dicts("SELECT * FROM users WHERE active = ?", True)
user = db.get_dict("SELECT * FROM users WHERE id = ?", 42)
names = db.get_column("SELECT name FROM users")
count = db.get_value("SELECT COUNT(*) FROM users")
rows = db.get_rows("SELECT * FROM users")  # list of lists
row = db.get_row("SELECT * FROM users WHERE id = ?", 42)
# Update (returns affected count)
n = db.update("users", {"name": "John"}, "id = ?", 42)
# Delete (returns affected count)
n = db.delete("users", "id = ?", 42)
# Upsert
db.upsert("users", {"email": "jan@x.com", "name": "Jan"}, on="email")
db.upsert("stats", {"user_id": 1, "views": 100}, on=["user_id"], update=["views"])
```

## Query Helpers

```py
# Find with kwargs
users = db.find("users", active=True, role="admin")
users = db.find("users", order="created DESC", limit=10)
user = db.find_one("users", id=42)
# Count and exists
total = db.count("users")
active = db.count("users", "active = ?", True)
if db.exists("users", "email = ?", "jan@x.com"):
  ...
# Pagination
result = db.paginate("SELECT * FROM users", page=2, per_page=20)
# {"items": [...], "total": 150, "page": 2, "pages": 8}
```

## Transactions

```py
with db.transaction():
  db.insert("orders", {"user_id": 1, "total": 99.50})
  db.update("users", {"balance": 0}, "id = ?", 1)
  # commits on success, rolls back on exception

# Batch execute
db.exec_batch("CREATE TABLE a (id INT); CREATE TABLE b (id INT)")
db.exec_batch([
  ("INSERT INTO users (name) VALUES (?)", "Jan"),
  ("INSERT INTO logs (msg) VALUES (?)", "created"),
])
```

## Async

```py
db = AsyncDatabase("postgres", "mydb", user="postgres", password="secret")
users = await db.get_dicts("SELECT * FROM users")
await db.insert("users", {"name": "Jan"})
user = await db.find_one("users", id=42)
async with db.transaction():
  await db.insert("orders", {"user_id": 1})
  await db.update("users", {"balance": 0}, "id = ?", 1)
```

## Connection Pooling (Async)

Async backends use connection pooling: pool is created lazily on first query.
No code changes needed, existing usage works as before.

For explicit lifecycle _(recommended for services)_:

```py
db = AsyncDatabase("postgres", "mydb", user="postgres", password="secret")
await db.start() # create pool eagerly, fail fast if DB unreachable
# ... use db ...
await db.close() # clean shutdown

# or as context manager:
async with AsyncDatabase("postgres", "mydb", user="postgres", password="secret") as db:
  await db.insert("users", {"name": "Jan"})
```

FastAPI lifespan:

```py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
  await db.start()
  yield
  await db.close()

app = FastAPI(lifespan=lifespan)
```

Pool configuration _(direct class import)_:

```py
from xaeian.db import PostgresAsyncDatabase, MysqlAsyncDatabase

db = PostgresAsyncDatabase("mydb", user="postgres", password="secret",
  min_pool=2, max_pool=20)
db = MysqlAsyncDatabase("mydb", user="root", password="secret",
  min_pool=2, max_pool=20)
```

Raw pool access for advanced operations _(COPY protocol, cursors)_:

```py
async with db.pool.acquire() as conn:
  await conn.copy_from_query("SELECT * FROM users", format="csv", header=True)
```

SQLite uses a single persistent connection with WAL mode instead of pooling.
Sync backends don't use pooling: each query opens a new connection.

## Key-Value Store

```py
from xaeian.db import Database, KeyValue, AsyncKeyValue

# Sync
db = Database("sqlite", "app.db")
kv = KeyValue(db)
kv.set("active_table", "pilot")
kv.get("active_table")       # "pilot"
kv.all()                     # {"active_table": "pilot", ...}
kv.delete("active_table")

# Async
db = AsyncDatabase("postgres", "mydb", user="postgres", password="secret")
kv = AsyncKeyValue(db)
await kv.set("maintenance", "true")
await kv.get("maintenance")  # "true"
await kv.all()               # {"maintenance": "true", ...}
```

Custom table name:
```py
kv = KeyValue(db, table="_settings")
```

## Auto-Conversion

```py
# dict/list → JSON (on insert)
db.insert("events", {"data": {"key": "value"}})
# ISO string → datetime (on insert)
db.insert("logs", {"created": "2024-01-15T10:30:00Z"})
# JSON parsing (on select)
# Single value
data = db.get_value("SELECT data FROM events WHERE id = ?", 1, json=True)
# Column of JSON values
configs = db.get_column("SELECT config FROM users", json=True)
# Rows by index (0-based)
rows = db.get_rows("SELECT id, data, meta FROM events", json=[1, 2])
row = db.get_row("SELECT id, data FROM events WHERE id = ?", 1, json=[1])
# Dicts by column name
users = db.get_dicts("SELECT * FROM users", json=["settings", "meta"])
user = db.get_dict("SELECT * FROM users WHERE id = ?", 1, json=["settings"])
user = db.find_one("users", json=["config"], id=42)
users = db.find("users", json=["config"], active=True)
result = db.paginate("SELECT * FROM events", json=["data"], page=1)
# Single param without tuple
db.get_dict("SELECT * FROM users WHERE id = ?", user_id)
```

## Utilities

```py
db.ping() # health check
db.debug = True # print all queries
db.has_table("users") # True/False
db.tables() # ["users", "orders", ...]
db.drop_table("temp")
db.drop_table("a", "b", "c") # multiple
db.has_database("mydb")
db.create_database("newdb")
db.drop_database("olddb")
```

## Logging

```py
from xaeian import logger, Print

# daemon / API
db = Database("sqlite", "app.db", log=logger("app"))

# script / CLI
db = Database("mysql", "mydb", user="root", password="secret", log=Print())
```

Errors are always raised as `DatabaseError` regardless of `log`.
`log` only adds an additional error line to the logger/terminal.

## Error Handling

```py
from xaeian.db import DatabaseError

try:
  db.insert("users", {"name": "Jan"})
except DatabaseError as e:
  print(e.op, e.sql, e.cause)
```

## Direct Class Import

```py
from xaeian.db import SqliteDatabase, MysqlDatabase, PostgresDatabase
from xaeian.db import SqliteAsyncDatabase, MysqlAsyncDatabase, PostgresAsyncDatabase

db = SqliteDatabase("app.db")
db = MysqlDatabase("mydb", host="localhost", user="root", password="secret", port=3306)
db = PostgresDatabase("mydb", host="localhost", user="postgres", password="secret", port=5432)
```

## Placeholders

All backends accept `?` placeholders. Converted automatically:
- SQLite: `?`
- MySQL: `?` → `%s`
- PostgreSQL: `?` → `$1`, `$2`, ...

```py
# Works on all backends
db.get_dicts("SELECT * FROM users WHERE id = ? AND active = ?", (42, True))
```