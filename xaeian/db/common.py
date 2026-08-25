# xaeian/db/common.py

"""What the sync and async halves share: dialect facts, error wrapping, field defaults."""
from __future__ import annotations

from typing import NoReturn
from ..log import Logger, Print
from .errors import DatabaseError
from .utils import to_driver, ident

class DatabaseCore:
  """
  Connection facts and error handling behind both `Database` and `AsyncDatabase`.

  A backend states how its driver differs in three class attributes:

    style: how the driver spells a placeholder; `?` is what callers write.
    quote: the identifier quote character.
    excluded: the conflict-row alias in upsert, `None` for MySQL's `ON DUPLICATE KEY`.
  """
  style = "?"
  quote = '"'
  excluded = "excluded"

  def __init__(self) -> None:
    self.db_name: str|None = None
    self.log: Logger|Print|None = None
    self.debug: bool = False

  def __repr__(self) -> str:
    return f"<{self.__class__.__name__} db={self.db_name!r}>"

  def _sql(self, sql:str) -> str:
    """Placeholders in the driver's own form; `?` is what the builders and the caller write."""
    return to_driver(sql, self.style)

  def _err(self, op:str, exc:Exception, sql:str|None=None, params:tuple|None=None) -> NoReturn:
    err = DatabaseError(op, exc, sql=sql, params=params)
    if self.log: self.log.err(f"[{self.db_name or 'db'}] {err}")
    raise err from exc

  def _debug(self, op:str, sql:str, params:tuple):
    s = " ".join(sql.split())[:100]
    msg = f"[{self.db_name or 'db'}] {op}: {s} {params or ''}"
    if self.log: self.log.dbg(msg)
    else: print(msg)

  def _rowcount(self, cur) -> int:
    """Row count clamped to 0, since drivers report -1 when it is unknown."""
    return max(0, cur.rowcount) if cur.rowcount is not None else 0

  def _valid_db(self, name:str|None) -> str:
    """The database name, checked and handed back so the caller holds a `str`, not a maybe."""
    if not name: raise ValueError("db_name required")
    ident(name)
    return name
