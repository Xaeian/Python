from __future__ import annotations
from datetime import datetime, timedelta
import calendar, pytz, tzlocal, re
from typing import Union, overload

TIME_INPUT = Union[str, int, float, datetime, timedelta, None]

class TIME(datetime):

  @overload
  def __new__(cls, v:TIME_INPUT = ...) -> TIME: ...

  @overload
  def __new__(cls, year:int, month:int, day:int,
    our:int, minute:int, second:int,
    microsecond:int=0, tzinfo:object = ...) -> TIME: ...
  
  def __new__(self, *args, **kwargs):
    if not args and not kwargs: return self.Create("now")
    elif len(args) == 1 and not kwargs: return self.Create(args[0])
    return datetime.__new__(self, *args, **kwargs)

  @staticmethod
  def fromDatatime(dt:datetime|TIME) -> TIME:
    return datetime.__new__(TIME,
      dt.year, dt.month, dt.day,
      dt.hour, dt.minute, dt.second,
      dt.microsecond, tzinfo=dt.tzinfo
    )
  
  def toDatatime(self) -> datetime:
    return datetime(
      self.year, self.month, self.day,
      self.hour, self.minute, self.second,
      self.microsecond, tzinfo=self.tzinfo
    )

  def to(self, format:str) -> float|TIME|str:
    comand = format.strip().lower()
    match comand:
      case "s"|"second"|"ts"|"timestamp": return self.timestamp()
      case "ms"|"millisecond": return self.timestamp() * 1000
      case "utc": return self.astimezone(pytz.utc)
      case "local": return  self.astimezone(tzlocal.get_localzone())
    if comand.startswith("tz") or comand.startswith("iso"):
      zone = comand.removeprefix("tz").removeprefix("iso").lstrip(":")
      if not zone: timezone = tzlocal.get_localzone()
      elif zone.lower() == "utc": timezone = pytz.utc
      else: timezone = pytz.timezone(zone)
      dt = self.astimezone(timezone)
      dtstr = dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + dt.strftime("%z")
      return dtstr[:-2] + ":" + dtstr[-2:]
    return self.strftime(format)

  def copy(self):
    return self.replace()

  def round(self, unit:str) -> TIME:
    unit = unit.lower()
    dt = self
    match unit:
      case "ms"|"millisecond":
        micros = (self.microsecond // 1000) * 1000
        dt = self.replace(microsecond=micros)
      case "s"|"second": dt = self.replace(microsecond=0)
      case "m"|"minute": dt = self.replace(second=0, microsecond=0)
      case "h"|"hour": dt = self.replace(minute=0, second=0, microsecond=0)
      case "d"|"day": dt = self.replace(hour=0, minute=0, second=0, microsecond=0)
      case "w"|"week":
        start:TIME = self - timedelta(days=self.weekday())
        dt = start.replace(hour=0, minute=0, second=0, microsecond=0)
      case "mo"|"month": dt = self.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
      case "y"|"year": dt = self.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
      case _: raise ValueError("Invalid unit: expected: 'ms', 's', 'm', 'h', 'd', 'w', 'mo' or 'y'")
    return TIME(dt)

  def __add__(self, v:str|int|float) -> TIME:
    if type(v) in (int, float):
      return TIME(self.timestamp() + v)
    elif type(v) is timedelta:
      return TIME.fromDatatime(datetime.__add__(self, v))
    elif type(v) is str:
      if TIME.isInterval(v): return TIME.Interval(v, self)
      elif TIME.isIntervals(v): return TIME.Intervals(v, self)
      else: raise ValueError(f"Invalid interval: {v}")
    else: raise TypeError(f"Unsupported '+' operand: TIME and {type(v).__name__}")

  def __sub__(self, v: TIME_INPUT="now") -> TIME|timedelta:
    if v is None or (type(v) is str and v.lower() == "now"):
      return timedelta(seconds=self.timestamp() - TIME.now().timestamp())
    if type(v) in (int, float):
      return TIME(self.timestamp() - v)
    if type(v) in (datetime, TIME):
      return timedelta(seconds=self.timestamp() - TIME.Create(v).timestamp())
    if type(v) is str:
      if TIME.isInterval(v):
        flipped = "-" + v if not v.startswith("-") else "+" + v[1:]
        return TIME.Interval(flipped, self)
      if type(v) is str and TIME.isIntervals(v):
        flipped = []
        for i in v.split():
          if i.startswith("-"):
            flipped.append("+" + i[1:])
          elif i.startswith("+"):
            flipped.append("-" + i[1:])
          else:
            flipped.append("-" + i)
        return TIME.Intervals(" ".join(flipped), self)
      raise ValueError(f"Invalid interval: '{v}'")
    raise TypeError(f"Unsupported '-' operand: TIME and {type(v).__name__}")

  @staticmethod
  def __Compare(v: TIME_INPUT) -> TIME:
    try: return TIME.Create(v).to("UTC")
    except Exception: return NotImplemented

  def __eq__(self, v): return datetime.__eq__(self.to("UTC"), TIME.__Compare(v))
  def __lt__(self, v): return datetime.__lt__(self.to("UTC"), TIME.__Compare(v))
  def __le__(self, v): return datetime.__le__(self.to("UTC"), TIME.__Compare(v))
  def __gt__(self, v): return datetime.__gt__(self.to("UTC"), TIME.__Compare(v))
  def __ge__(self, v): return datetime.__ge__(self.to("UTC"), TIME.__Compare(v))

  def between(self, low:TIME, high:TIME, inclusive=True):
    if inclusive: return low <= self <= high
    else: return low < self < high

  def __str__(self):
    if self.microsecond == 0: return self.strftime("%Y-%m-%d %H:%M:%S")
    else: return self.strftime("%Y-%m-%d %H:%M:%S.%f")

  def __repr__(self):
    iso = self.to("iso")
    return f"TIME({iso})"
  
  @staticmethod
  def Interval(interval:str="", dt:None|datetime|TIME=None) -> TIME:
    dt = datetime.now() if dt is None else dt.toDatatime() if type(dt) is TIME else dt
    value = re.findall(r"\-?[0-9]*\.?[0-9]+", interval)
    if not value: return dt
    value = float(value[0])
    factor = re.sub("[^a-z]", "", interval.lower())
    if factor == "y" or factor == "mo":
      if factor == "y": value *= 12
      month = dt.month - 1 + int(value)
      year = dt.year + month // 12
      month = month % 12 + 1
      day = min(dt.day, calendar.monthrange(year, month)[1])
      return dt.replace(year, month, day)
    match factor:
      case "w": dt += timedelta(weeks=value)
      case "d": dt += timedelta(days=value)
      case "h": dt += timedelta(hours=value)
      case "m": dt += timedelta(minutes=value)
      case "s": dt += timedelta(seconds=value)
      case "ms": dt += timedelta(milliseconds=value)
      case "us"|"µs": dt += timedelta(microseconds=value)
    return TIME.fromDatatime(dt)

  @staticmethod
  def Intervals(intervals: str = "", dt: None | datetime | TIME = None) -> TIME:
    dt = datetime.now() if dt is None else dt.toDatatime() if type(dt) is TIME else dt
    if " " in intervals:
      tokens = intervals.split()
    else:
      pattern = r"[+\-]?[0-9]*\.?[0-9]+(?:y|mo|w|d|h|m|s|ms|µs|us)"
      tokens = re.findall(pattern, intervals)
      if tokens and tokens[0]:
        first_sign = tokens[0][0] if tokens[0][0] in "+-" else ""
        if first_sign:
          tokens = [token if token[0] in "+-" else first_sign + token for token in tokens]
    for token in tokens:
      dt = TIME.Interval(token, dt)
    return TIME.fromDatatime(dt)

  @staticmethod
  def isInterval(text:str):
    pattern = r"[\+\-]?[0-9]*\.?[0-9]+(y|mo|w|d|h|m|s|ms|µs|us)"
    return bool(re.fullmatch(pattern, text.strip()))

  @staticmethod
  def isIntervals(text: str) -> bool:
    pattern = r"^(?:[+\-]?[0-9]*\.?[0-9]+(?:y|mo|w|d|h|m|s|ms|µs|us)\s*)+$"
    return bool(re.fullmatch(pattern, text.strip()))

  @staticmethod
  def Create(v: TIME_INPUT = "now") -> TIME | None:
    if v is None:
      return None
    if type(v) is timedelta:
      now = datetime.now(tz=tzlocal.get_localzone())
      now = now + v
      return TIME.fromDatatime(now)
    if type(v) in (int, float): return TIME.fromDatatime(datetime.fromtimestamp(v))      
    if type(v) in (datetime, TIME): return TIME.fromDatatime(v)
    vstr = str(v).strip()
    if vstr.lower() == "now": return TIME.fromDatatime(datetime.now(tz=tzlocal.get_localzone()))   
    if vstr.replace(".", "", 1).isdigit(): return TIME.fromDatatime(datetime.fromtimestamp(float(vstr)))    
    if TIME.isInterval(vstr): return TIME.Interval(vstr)
    if TIME.isIntervals(vstr): return TIME.Intervals(vstr)
    vstr = vstr.replace("T", " ").replace(",", ".")
    patterns = [
      ('%Y-%m-%d',             r"\d{4}-\d{2}-\d{2}"),
      ('%d-%m-%Y',             r"\d{2}-\d{2}-\d{4}"),
      ('%d.%m.%Y',             r"\d{2}\.\d{2}\.\d{4}"),
      ('%Y/%m/%d',             r"\d{4}/\d{2}/\d{2}"),
      ('%Y%m%d',               r"\d{8}"),
      ('%Y-%m-%d %H:%M',       r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
      ('%Y-%m-%d %H:%M:%S',    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
      ('%Y-%m-%d %H:%M:%S.%f', r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6}"),
      ('%d.%m.%Y %H:%M',       r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}"),
      ('%d.%m.%Y %H:%M:%S',    r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}"),
      ('%d.%m.%Y %H:%M:%S.%f', r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\.\d{3,6}"),
      ('%m/%d/%y',             r"\d{2}/\d{2}/\d{2}"),
      ('%m/%d/%y %H:%M',       r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}"),
      ('%m/%d/%y %H:%M:%S',    r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"),
      ('%m/%d/%y %H:%M:%S.%f', r"\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6}")
    ]
    for format, pattern in patterns:
      if re.fullmatch(pattern, vstr):
        try: return TIME.fromDatatime(datetime.strptime(vstr, format))
        except ValueError: continue
    return None

if __name__ == "__main__":
    t1 = TIME()  # current time ("now")
    t2 = TIME("2025-03-01 12:00")  # specific datetime ("YYYY-MM-DD HH:MM")
    t2_alt = TIME("03/01/25 12:00:00")  # alternative format ("MM/DD/YY HH:MM:SS")
    t3 = TIME("2d")  # now + 2 days
    t4 = TIME("-6h 20m")  # flux: -6h then +20m
    t5 = TIME("-6h20m")  # flux: -6h and -20m (no space)
    t6 = t5.round("h")  # round to nearest hour
    t7 = t2.round("d")  # round to start of day
    t8 = t2 + "1w"  # add 1 week
    t9 = t2 - "3d"  # subtract 3 days
    diff = t2 - t1  # difference (timedelta)
    comp1 = t1 < t2
    comp2 = t1 >= t2
    utc_format = t2.to("utc")
    alt_tz = t2.to("tz:America/New_York")  # specific timezone conversion
    timestamp = t2.to("ts")
    timestamp_ms = t2.to("ms")
    custom_format = t2.to("%d.%m.%Y %H:%M:%S")
    t10 = TIME(1700000000)  # from timestamp
    t11 = TIME(timedelta(days=1, hours=5, minutes=30))  # now + delta
    sorted_times = sorted([t2, t1, t8, t9, t10, t11])
    print("now:", t1)
    print("t2:", t2)
    print("Alt format:", t2_alt)
    print("now + 2d:", t3)
    print("Flux1 (-6h 20m):", t4)
    print("Flux2 (-6h20m):", t5)
    print("Flux2 rounded to hour:", t6)
    print("t2 rounded to day:", t7)
    print("t2 + 1w:", t8)
    print("t2 - 3d:", t9)
    print("Difference:", diff)
    print("now < t2?:", comp1)
    print("now >= t2?:", comp2)
    print("UTC format:", utc_format)
    print("ISO format:", alt_tz)
    print("Timestamp:", timestamp)
    print("Timestamp(ms):", timestamp_ms)
    print("Custom format:", custom_format)
