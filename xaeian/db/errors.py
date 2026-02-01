# xaeian/db/errors.py

"""Database errors."""
from __future__ import annotations

class DatabaseError(RuntimeError):
  """
  Database operation failed.

  Wraps driver-specific exceptions with operation context.

  Args:
    op: Operation name (`"exec"`, `"insert"`, `"get_dicts"`).
    cause: Original exception from database driver.
    sql: SQL statement that failed.
    params: Parameters passed to statement.

  Attributes:
    op: Operation name.
    cause: Original exception.
    sql: Failed SQL statement.
    params: Statement parameters.

  Example:
    >>> try:
    ...   db.exec("INVALID SQL")
    ... except DatabaseError as e:
    ...   print(e.op, e.cause)
  """
  def __init__(
    self,
    op: str,
    cause: Exception,
    sql: str|None = None,
    params: tuple|None = None,
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
