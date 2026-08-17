# xaeian/db/errors.py

"""Database errors."""
from __future__ import annotations

class DatabaseError(RuntimeError):
  """
  Database operation failed, wrapping the driver exception.

  Keeps `op` (method name), `cause`, `sql` and `params` of the failing call as attributes.
  The message carries `op`, `cause` and the SQL clipped to 200 chars, never `params`, so
  logging it cannot leak values.
  """
  def __init__(
    self,
    op:str,
    cause:Exception,
    sql:str|None = None,
    params:tuple|None = None,
  ):
    self.op = op
    self.cause = cause
    self.sql = sql
    self.params = params
    msg = f"{op}: {cause}"
    if sql:
      s = " ".join(str(sql).split())
      msg += f" | {s[:200]}..." if len(s) > 200 else f" | {s}"
    super().__init__(msg)
