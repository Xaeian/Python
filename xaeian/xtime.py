# xaeian/xtime.py

"""
Extended datetime with human-friendly interface.

Provides `Time` class extending `datetime` with:
- Flexible parsing (strings, timestamps, intervals)
- Interval arithmetic (`t + "1w"`, `t - "3d"`)
- Multiple output formats (`to("iso")`, `to("ts")`)
- Rounding to time units (`round("h")`, `round("d")`)

Requires: `pytz`, `tzlocal`

Example:
  >>> from xaeian.xtime import Time
  >>> t = Time()              # current local time
  >>> t = Time("2025-03-01")  # parse date
  >>> t = Time("2d")          # now + 2 days
  >>> t + "1w"                # add 1 week
  >>> t.to("iso")             # ISO 8601 string
  >>> t.round("h")            # round to hour
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Union, overload
import calendar
import re

try:
  import pytz, tzlocal
except ImportError:
  raise ImportError("Install with: pip install xaeian[time]")

TimeInput = Union[str, int, float, datetime, timedelta, "Time"]

class Time(datetime):
  """
  Extended `datetime` with human-friendly interface.

  **Creation:**
  - `Time()` — current local time
  - `Time("2025-03-01 12:00")` — parse datetime string
  - `Time(1700000000)` — from unix timestamp
  - `Time("2d")` — now + 2 days
  - `Time("-6h 30m")` — now - 6 hours + 30 minutes

  **Arithmetic:**
  - `t + "1w"` — add 1 week
  - `t - "3d"` — subtract 3 days
  - `t - other` — timedelta between two times

  **Formatting via `to()`:**
  - `t.to("ts")` — unix timestamp (float)
  - `t.to("utc")` — convert to UTC
  - `t.to("iso")` — ISO 8601 string
  - `t.to("%Y-%m-%d")` — strftime format

  **Rounding via `round()`:**
  - `t.round("h")` — round to hour start
  - `t.round("d")` — round to day start
  - `t.round("w")` — round to week start (Monday)
  - `t.round("mo")` — round to month start
  """

  #------------------------------------------------------------------------------------- Construction

  @overload
  def __new__(cls, v:TimeInput=...) -> Time: ...

  @overload
  def __new__(cls, year:int, month:int, day:int,
    hour:int=0, minute:int=0, second:int=0,
    microsecond:int=0, tzinfo:object=None) -> Time: ...

  def __new__(cls, *args, **kwargs):
    if not args and not kwargs: return cls._now()
    if len(args) == 1 and not kwargs: return cls._parse(args[0])
    return datetime.__new__(cls, *args, **kwargs)

  def __hash__(self) -> int:
    return super().__hash__()

  @classmethod
  def _from_datetime(cls, dt:datetime) -> Time:
    """Convert datetime to `Time`."""
    return datetime.__new__(cls,
      dt.year, dt.month, dt.day,
      dt.hour, dt.minute, dt.second,
      dt.microsecond, tzinfo=dt.tzinfo
    )

  @classmethod
  def _now(cls) -> Time:
    """Current time in local timezone."""
    return cls._from_datetime(datetime.now(tz=tzlocal.get_localzone()))

  def to_datetime(self) -> datetime:
    """Convert `Time` to standard datetime."""
    return datetime(
      self.year, self.month, self.day,
      self.hour, self.minute, self.second,
      self.microsecond, tzinfo=self.tzinfo
    )

  def copy(self) -> Time:
    """Create a copy of this `Time` instance."""
    return Time._from_datetime(self.replace())

  #--------------------------------------------------------------------------------------- Formatting

  def to(self, fmt:str) -> float|int|str|Time:
    """
    Convert/format `Time`.

    Args:
      fmt: Format specifier:
        - "ts"|"timestamp": Unix seconds (float)
        - "s"|"second": Unix seconds (int)
        - "ms"|"millisecond": Unix milliseconds (int)
        - "utc"|"local": timezone conversion
        - "iso": ISO 8601 string
        - "tz:Zone/Name": convert to timezone
        - other: passed to `strftime`

    Returns:
      float|int|Time|str depending on fmt.
    """
    raw = fmt.strip()
    cmd = raw.lower()
    match cmd:
      case "ts"|"timestamp": return self.timestamp()
      case "s"|"second": return int(self.timestamp())
      case "ms"|"millisecond": return int(self.timestamp() * 1000)
      case "utc": return Time._from_datetime(self.astimezone(pytz.utc))
      case "local": return Time._from_datetime(self.astimezone(tzlocal.get_localzone()))
      case "iso":
        dt = self
        if dt.tzinfo is None: dt = dt.replace(tzinfo=tzlocal.get_localzone())
        return dt.isoformat(timespec="seconds")
    if cmd.startswith("tz:") or cmd.startswith("iso:"):
      zone = raw.split(":", 1)[1].strip()
      if not zone: tz = self.tzinfo or tzlocal.get_localzone()
      elif zone.lower() == "utc": tz = pytz.utc
      else: tz = pytz.timezone(zone)
      dt = self.astimezone(tz)
      return dt.isoformat(timespec="seconds")
    return self.strftime(fmt)

  #----------------------------------------------------------------------------------------- Rounding

  def round(self, unit:str) -> Time:
    """
    Round Time down to specified unit.

    Args:
      unit: ms, s, m, h, d, w, mo, y
    """
    match unit.lower():
      case "ms"|"millisecond":
        us = (self.microsecond // 1000) * 1000
        dt = self.replace(microsecond=us)
      case "s"|"second": dt = self.replace(microsecond=0)
      case "m"|"minute": dt = self.replace(second=0, microsecond=0)
      case "h"|"hour": dt = self.replace(minute=0, second=0, microsecond=0)
      case "d"|"day": dt = self.replace(hour=0, minute=0, second=0, microsecond=0)
      case "w"|"week":
        start = self - timedelta(days=self.weekday())
        dt = start.replace(hour=0, minute=0, second=0, microsecond=0)
      case "mo"|"month": dt = self.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
      case "y"|"year": dt = self.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
      case _: raise ValueError(f"Invalid unit '{unit}', expected: ms, s, m, h, d, w, mo, y")
    return Time._from_datetime(dt)

  #--------------------------------------------------------------------------------------- Arithmetic

  def __add__(self, v:str|int|float|timedelta) -> Time:
    """Add interval, seconds, or timedelta."""
    if isinstance(v, (int, float)):
      return Time._from_datetime(datetime.fromtimestamp(
        self.timestamp() + v, tz=self.tzinfo or tzlocal.get_localzone()
      ))
    if isinstance(v, timedelta): return Time._from_datetime(datetime.__add__(self, v))
    if isinstance(v, str): return self._apply_intervals(v)
    raise TypeError(f"Unsupported operand: Time + {type(v).__name__}")

  def __radd__(self, v:int|float|timedelta) -> Time:
    return self.__add__(v)

  def __sub__(self, v:TimeInput|None) -> Time|timedelta:
    """Subtract interval/seconds/timedelta (→ Time) or datetime (→ timedelta)."""
    if v is None: return self
    if isinstance(v, (int, float)):
      return Time._from_datetime(datetime.fromtimestamp(
        self.timestamp() - v, tz=self.tzinfo or tzlocal.get_localzone()
      ))
    if isinstance(v, timedelta): return Time._from_datetime(datetime.__sub__(self, v))
    if isinstance(v, (datetime, Time)):
      return timedelta(seconds=self.timestamp() - Time._parse(v).timestamp())
    if isinstance(v, str): return self._apply_intervals(self._flip_intervals(v))
    raise TypeError(f"Unsupported operand: Time - {type(v).__name__}")

  #--------------------------------------------------------------------------------------- Comparison

  def _to_utc(self) -> datetime:
    if self.tzinfo is None:
      return self.replace(tzinfo=tzlocal.get_localzone()).astimezone(pytz.utc)
    return self.astimezone(pytz.utc)

  @staticmethod
  def _safe_parse(v:TimeInput) -> datetime|None:
    try:
      t = Time._parse(v)
      if t.tzinfo is None:
        return t.replace(tzinfo=tzlocal.get_localzone()).astimezone(pytz.utc)
      return t.astimezone(pytz.utc)
    except Exception:
      return None

  def __eq__(self, v) -> bool:
    other = Time._safe_parse(v)
    if other is None: return NotImplemented
    return datetime.__eq__(self._to_utc(), other)

  def __ne__(self, v) -> bool:
    result = self.__eq__(v)
    if result is NotImplemented: return result
    return not result

  def __lt__(self, v) -> bool:
    other = Time._safe_parse(v)
    if other is None: return NotImplemented
    return datetime.__lt__(self._to_utc(), other)

  def __le__(self, v) -> bool:
    other = Time._safe_parse(v)
    if other is None: return NotImplemented
    return datetime.__le__(self._to_utc(), other)

  def __gt__(self, v) -> bool:
    other = Time._safe_parse(v)
    if other is None: return NotImplemented
    return datetime.__gt__(self._to_utc(), other)

  def __ge__(self, v) -> bool:
    other = Time._safe_parse(v)
    if other is None: return NotImplemented
    return datetime.__ge__(self._to_utc(), other)

  def between(self, low:TimeInput, high:TimeInput, inclusive:bool=True) -> bool:
    """Check if `Time` is between two bounds."""
    lo, hi = Time._parse(low), Time._parse(high)
    if inclusive: return lo <= self <= hi
    return lo < self < hi

  #------------------------------------------------------------------------------------------- String

  def __str__(self) -> str:
    if self.microsecond: return self.strftime("%Y-%m-%d %H:%M:%S.%f")
    return self.strftime("%Y-%m-%d %H:%M:%S")

  def __repr__(self) -> str:
    return f"Time({self.to('iso')})"

  #---------------------------------------------------------------------------------- Interval parsing

  INTERVAL_PATTERN = r"[+\-]?[0-9]*\.?[0-9]+(?:y|mo|w|d|h|m|s|ms|µs|us)"
  INTERVAL_RE = re.compile(INTERVAL_PATTERN)
  INTERVALS_RE = re.compile(rf"^(?:{INTERVAL_PATTERN}\s*)+$")

  @classmethod
  def is_interval(cls, text:str) -> bool:
    """Check if text is valid single interval."""
    return bool(cls.INTERVAL_RE.fullmatch(text.strip()))

  @classmethod
  def is_intervals(cls, text:str) -> bool:
    """Check if text is valid interval sequence."""
    return bool(cls.INTERVALS_RE.fullmatch(text.strip()))

  def _apply_interval(self, interval:str) -> Time:
    match = re.search(r"-?[0-9]*\.?[0-9]+", interval)
    if not match: return self
    value = float(match.group())
    unit = re.sub(r"[^a-zµ]", "", interval.lower())
    dt = self.to_datetime()
    if unit in ("y", "mo"):
      months = int(value * 12) if unit == "y" else int(value)
      month = dt.month - 1 + months
      year = dt.year + month // 12
      month = month % 12 + 1
      day = min(dt.day, calendar.monthrange(year, month)[1])
      return Time._from_datetime(dt.replace(year=year, month=month, day=day))
    match unit:
      case "w":  delta = timedelta(weeks=value)
      case "d":  delta = timedelta(days=value)
      case "h":  delta = timedelta(hours=value)
      case "m":  delta = timedelta(minutes=value)
      case "s":  delta = timedelta(seconds=value)
      case "ms": delta = timedelta(milliseconds=value)
      case "µs"|"us": delta = timedelta(microseconds=value)
      case _: return self
    return Time._from_datetime(dt + delta)

  def _apply_intervals(self, text:str) -> Time:
    text = text.strip()
    tokens = text.split() if " " in text else self.INTERVAL_RE.findall(text)
    result = self
    for token in tokens: result = result._apply_interval(token)
    return result

  @classmethod
  def _flip_intervals(cls, text:str) -> str:
    text = text.strip()
    tokens = text.split() if " " in text else cls.INTERVAL_RE.findall(text)
    flipped = []
    for t in tokens:
      if t.startswith("-"): flipped.append("+" + t[1:])
      elif t.startswith("+"): flipped.append("-" + t[1:])
      else: flipped.append("-" + t)
    return " ".join(flipped)

  #------------------------------------------------------------------------------------------ Factory

  PARSE_PATTERNS = [
    ("%Y-%m-%d",             r"\d{4}-\d{2}-\d{2}"),
    ("%d-%m-%Y",             r"\d{2}-\d{2}-\d{4}"),
    ("%d.%m.%Y",             r"\d{2}\.\d{2}\.\d{4}"),
    ("%Y/%m/%d",             r"\d{4}/\d{2}/\d{2}"),
    ("%Y%m%d",               r"\d{8}"),
    ("%Y-%m-%d %H:%M",       r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
    ("%Y-%m-%d %H:%M:%S",    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
    ("%Y-%m-%d %H:%M:%S.%f", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6}"),
    ("%d.%m.%Y %H:%M",       r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}"),
    ("%d.%m.%Y %H:%M:%S",    r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}"),
    ("%d.%m.%Y %H:%M:%S.%f", r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\.\d{3,6}"),
    ("%m/%d/%y",             r"\d{2}/\d{2}/\d{2}"),
    ("%m/%d/%y %H:%M",       r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}"),
    ("%m/%d/%y %H:%M:%S",    r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"),
    ("%m/%d/%y %H:%M:%S.%f", r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6}"),
  ]

  @classmethod
  def _parse(cls, v:TimeInput) -> Time:
    """Parse input to Time. Raises ValueError/TypeError on failure."""
    if isinstance(v, Time): return v
    if isinstance(v, datetime): return cls._from_datetime(v)
    if isinstance(v, timedelta):
      return cls._from_datetime(datetime.now(tz=tzlocal.get_localzone()) + v)
    if isinstance(v, (int, float)):
      return cls._from_datetime(datetime.fromtimestamp(v, tz=tzlocal.get_localzone()))
    if not isinstance(v, str): raise TypeError(f"Cannot create Time from {type(v).__name__}")
    s = v.strip()
    if s.lower() == "now": return cls._now()
    if s.replace(".", "", 1).replace("-", "", 1).isdigit():
      return cls._from_datetime(datetime.fromtimestamp(float(s), tz=tzlocal.get_localzone()))
    if cls.is_interval(s): return cls._now()._apply_interval(s)
    if cls.is_intervals(s): return cls._now()._apply_intervals(s)
    try: return cls._from_datetime(datetime.fromisoformat(s))
    except ValueError: pass
    norm = s.replace("T", " ").replace(",", ".")
    for fmt, pattern in cls.PARSE_PATTERNS:
      if re.fullmatch(pattern, norm):
        try: return cls._from_datetime(datetime.strptime(norm, fmt))
        except ValueError: continue
    raise ValueError(f"Cannot parse time: '{v}'")

def time_to(v:TimeInput|None, fmt:str) -> str|int|float|Time|None:
  """None/empty -> None, else Time(v).to(fmt)."""
  if v is None: return None
  if isinstance(v, str) and not v.strip(): return None
  return Time(v).to(fmt)

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  t1 = Time()
  t2 = Time("2025-03-01 12:00")
  t3 = Time("03/01/25 12:00:00")
  t4 = Time("2d")
  t5 = Time("-6h 30m")
  t7 = Time(1700000000)
  t8 = Time(timedelta(days=1, hours=5))
  t9 = Time("2025-03-01T12:00:00+02:00")
  print("now:", t1)
  print("parsed:", t2)
  print("alt format:", t3)
  print("now + 2d:", t4)
  print("-6h 30m:", t5)
  print("timestamp:", t7)
  print("timedelta:", t8)
  print("ISO with tz:", t9, "→", t9.to("iso"))
  print()
  print("t2 + 1w:", t2 + "1w")
  print("t2 - 3d:", t2 - "3d")
  print("t2 - t1:", t2 - t1)
  print()
  print("round(h):", t1.round("h"))
  print("round(d):", t1.round("d"))
  print("round(w):", t1.round("w"))
  print("round(mo):", t1.round("mo"))
  print()
  print("to(ts):", t2.to("ts"))
  print("to(iso):", t2.to("iso"))
  print("to(utc):", t2.to("utc"))
  print("to(tz:America/New_York):", t2.to("tz:America/New_York"))
  print("to(%d.%m.%Y):", t2.to("%d.%m.%Y"))
