# tests/test_xtime.py

"""Time: parsing, interval arithmetic, timezone-aware formatting, rounding."""

import re, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest, tzlocal
from xaeian import Time, time_to

# Aware inputs are used wherever the result depends on an instant (ts/utc/iso/tz);
# parsing and interval arithmetic are checked by wall-clock equality (tz-independent).

@pytest.mark.parametrize("text, ymdhms", [
  ("2025-03-01", (2025, 3, 1, 0, 0, 0)),
  ("01.03.2025", (2025, 3, 1, 0, 0, 0)),
  ("2025/03/01", (2025, 3, 1, 0, 0, 0)),
  ("03/01/25 14:30", (2025, 3, 1, 14, 30, 0)), # %m/%d/%y → March 1st
  ("2025-03-01 12:00:00", (2025, 3, 1, 12, 0, 0)),
])
def parses_common_formats(text, ymdhms):
  t = Time(text)
  assert (t.year, t.month, t.day, t.hour, t.minute, t.second) == ymdhms

def parses_datetime_and_timestamp():
  assert Time(datetime(2025, 3, 1, 12)).year == 2025
  assert Time(1700000000).to("ts") == 1700000000.0 # unix timestamp round-trips

def parsing_a_time_returns_same_object():
  t = Time("2025-03-01 12:00:00")
  assert Time(t) is t # idempotent: wrapping a Time yields the same instance

def rejects_unparseable_string():
  with pytest.raises(ValueError):
    Time("definitely not a date")

def a_timestamp_in_milliseconds_is_refused_in_plain_words():
  """Devices often send milliseconds; as seconds they lie past year 9999."""
  for stamp in (1761652800000, "1761652800000"):
    with pytest.raises(ValueError, match="milliseconds"):
      Time(stamp)

def rejects_unsupported_type():
  with pytest.raises(TypeError):
    Time(["nope"])

def adds_interval_keeps_wall_clock():
  base = Time("2025-03-01 12:00:00")
  assert base + "1w" == Time("2025-03-08 12:00:00")
  assert base + "3d" == Time("2025-03-04 12:00:00")
  assert base + "90m" == Time("2025-03-01 13:30:00")

def interval_1h2ms_adds_hour_and_millis():
  # "ms" beats "m": 1h2ms is +1h +2ms, not +1h +2min
  assert (Time("2025-03-01 12:00:00") + "1h2ms").to("%H:%M:%S.%f") == "13:00:00.002000"

def multi_token_interval_with_spaces():
  assert Time("2025-03-01 12:00") + "1d 2h" == Time("2025-03-02 14:00")
  assert Time("2025-03-01 12:00") + "-6h 30m" == Time("2025-03-01 06:30")

@pytest.mark.parametrize("bad", ["garbage", "5x"])
def rejects_invalid_interval_string(bad):
  with pytest.raises(ValueError):
    Time("2025-03-01 12:00") + bad
  with pytest.raises(ValueError):
    Time("2025-03-01 12:00") - bad

@pytest.mark.parametrize("far", ["999999999999s", "-99999999d", "99999999y"])
def an_interval_past_the_calendar_is_a_value_error_naming_it_as_written(far):
  said = f"Interval '{re.escape(far)}' out of range"
  with pytest.raises(ValueError, match=said):
    Time(0) + far
  with pytest.raises(ValueError, match=said):
    Time(0) - far

def whole_seconds_and_milliseconds_round_down_before_1970_too():
  late = Time("1900-06-01T12:00:00.750+00:00")
  assert Time(late.to("s")) == Time("1900-06-01T12:00:00+00:00")
  assert late.to("ms") - late.to("s") * 1000 == 750

def a_year_before_1970_or_after_3000_is_counted():
  """Seconds are counted, not asked of the OS: Windows refuses all of these."""
  old = Time("1900-01-01")
  assert Time(old.to("ts")) == old
  assert old + 60 == Time("1900-01-01 00:01")
  assert Time(0) - 86400 == Time(-86400) == Time("1969-12-31T00:00:00+00:00")
  assert Time(40000000000).to("s") == 40000000000
  assert Time("9999-12-31T23:59:59-05:00").to("ts") == 253402318799 # the calendar's last day

def a_timestamp_reads_back_to_the_same_time(monkeypatch):
  """
  Both ways read the zone's history, here Warsaw's, with no summer time in 1973.
  An OS that applies today's rules, as Windows does, or runs in another zone would shift it.
  """
  monkeypatch.setattr(tzlocal, "get_localzone", lambda: ZoneInfo("Europe/Warsaw"))
  summer = Time("1973-06-29 12:00")
  assert Time(summer.to("ts")) == summer

def two_times_of_one_zone_differ_by_the_time_that_passed(monkeypatch):
  """Warsaw moves its clock an hour ahead on 2025-03-30: two days by the clock are 47 hours."""
  monkeypatch.setattr(tzlocal, "get_localzone", lambda: ZoneInfo("Europe/Warsaw"))
  assert Time("2025-03-31 12:00") - Time("2025-03-29 12:00") == timedelta(hours=47)

def a_long_text_that_is_no_interval_is_refused_at_once():
  """Digits that split several ways would double the time every 3 characters: seconds here."""
  text = "99s" * 25 + "x"
  start = time.perf_counter()
  assert not Time.is_intervals(text)
  assert time.perf_counter() - start < 1

def fractional_time_intervals():
  base = Time("2025-03-01 12:00:00")
  assert base + "1.5h" == Time("2025-03-01 13:30:00")
  assert base + "0.5d" == Time("2025-03-02 00:00:00")

def fractional_calendar_units_truncate():
  # Months and years step by whole units: the fractional part is dropped
  assert Time("2025-03-01 12:00") + "2.5mo" == Time("2025-05-01 12:00") # +2 months, not +2.5
  assert Time("2025-03-01 12:00") + "0.5y" == Time("2025-09-01 12:00") # int(0.5*12) = 6 months

def microsecond_unit_accepts_mu_or_us():
  base = Time("2025-03-01 12:00:00")
  assert base + "5µs" == base + "5us" == Time("2025-03-01 12:00:00.000005")

def leading_plus_sign_is_positive():
  base = Time("2025-03-01")
  assert base + "+2d" == base + "2d" == Time("2025-03-03")

def timedelta_and_second_operands():
  assert Time("2025-03-01 12:00") + timedelta(days=1, hours=2) == Time("2025-03-02 14:00")
  aware = Time("2025-03-01T12:00:00+00:00")
  assert (aware + 90).to("iso") == "2025-03-01T12:01:30+00:00" # bare int = seconds
  assert (90 + aware).to("iso") == "2025-03-01T12:01:30+00:00" # reflected add

def subtract_interval_flips_sign():
  base = Time("2025-03-01")
  assert base - "2d" == base + "-2d" == Time("2025-02-27")

def month_add_clamps_to_last_day():
  assert Time("2025-01-31") + "1mo" == Time("2025-02-28") # Feb has no 31st

def year_add_clamps_leap_day():
  assert Time("2024-02-29") + "1y" == Time("2025-02-28") # 2025 is not a leap year

def difference_between_times_is_timedelta():
  delta = Time("2025-03-01 12:00") - Time("2025-03-01 10:00")
  assert isinstance(delta, timedelta) and delta.total_seconds() == 7200

def difference_can_be_negative():
  assert (Time("2025-03-01 10:00") - Time("2025-03-01 12:00")).total_seconds() == -7200

def compares_by_instant_across_zones():
  assert Time("2025-03-01T12:00:00+00:00") == Time("2025-03-01T13:00:00+01:00") # same instant
  assert Time("2025-03-01T12:00:00+00:00") < Time("2025-03-01T12:00:01+00:00")

def a_comparison_takes_only_a_time_or_a_datetime():
  """
  The frozen 1.0 contract: wrap the operand yourself.

  A string parsed inside `__eq__` would compare a typo as `False` instead of saying it is one,
  and could declare an unrelated object equal to a point in time.
  """
  t = Time("2025-03-01 12:00:00")
  assert t == Time("2025-03-01 12:00:00")
  assert t == datetime(2025, 3, 1, 12, 0, 0)
  assert t != "2025-03-01 12:00:00"
  assert t != t.timestamp()
  for other in ("2025-03-02", 1740000000, None):
    with pytest.raises(TypeError):
      t < other

def between_and_arithmetic_read_a_string():
  """Parsing is not comparing: `between` and the arithmetic take a string where a time goes."""
  t = Time("2025-03-01")
  assert t.between("2025-02-01", "2025-04-01")
  assert (t + "1d").to("iso").startswith("2025-03-02")
  assert Time("2025-03-01 12:00:00") == Time("2025-03-01 12:00:00")

def between_respects_inclusivity():
  t = Time("2025-03-01")
  assert t.between("2025-02-01", "2025-04-01")
  assert t.between("2025-03-01", "2025-04-01", inclusive=True)
  assert not t.between("2025-03-01", "2025-04-01", inclusive=False)

def formats_timestamp_variants():
  t = Time("2025-03-01T12:00:00+00:00")
  assert t.to("ts") == datetime(2025, 3, 1, 12, tzinfo=timezone.utc).timestamp()
  assert t.to("s") == int(t.to("ts"))
  assert t.to("ms") == int(t.to("ts")) * 1000

def converts_to_utc():
  assert Time("2025-03-01T12:00:00+02:00").to("utc").to("iso") == "2025-03-01T10:00:00+00:00"

def converts_to_named_timezone():
  assert Time("2025-03-01T12:00:00+00:00").to("tz:America/New_York") == "2025-03-01T07:00:00-05:00"

def iso_keeps_offset():
  assert Time("2025-03-01T12:00:00+00:00").to("iso") == "2025-03-01T12:00:00+00:00"

def strftime_passthrough():
  assert Time("2025-03-01T12:00:00+00:00").to("%d.%m.%Y") == "01.03.2025"

@pytest.mark.parametrize("unit, expected", [
  ("ms", "2025-03-05 14:37:23.123000"),
  ("s", "2025-03-05 14:37:23"),
  ("m", "2025-03-05 14:37:00"),
  ("h", "2025-03-05 14:00:00"),
  ("d", "2025-03-05 00:00:00"),
  ("mo", "2025-03-01 00:00:00"),
  ("y", "2025-01-01 00:00:00"),
])
def rounds_down_to_unit(unit, expected):
  assert str(Time("2025-03-05 14:37:23.123456").round(unit)) == expected

def rounds_week_to_monday():
  assert str(Time("2025-03-05 14:37:23").round("w")) == "2025-03-03 00:00:00" # Wed → Mon

def round_rejects_unknown_unit():
  with pytest.raises(ValueError):
    Time("2025-03-01").round("decade")

def distinguishes_single_interval_from_sequence():
  assert Time.is_interval("2ms")
  assert not Time.is_interval("1h2ms") # two tokens, not one interval
  assert Time.is_intervals("1h2ms")
  assert not Time.is_intervals("2025-03-01")

def copy_equals_but_is_new_object():
  t = Time("2025-03-01 12:00:00")
  c = t.copy()
  assert c == t and c is not t

def time_to_passes_through_none_and_blank():
  assert time_to(None, "iso") is None
  assert time_to("   ", "iso") is None
  noon_utc = datetime(2025, 3, 1, 12, tzinfo=timezone.utc)
  assert time_to("2025-03-01T12:00:00+00:00", "ts") == noon_utc.timestamp()

#-------------------------------------------------------------------------------------- regressions

def an_ambiguous_hour_keeps_the_pass_it_was_given():
  """Rebuilding the fields dropped `fold`, moving the second pass of a repeated hour by an hour."""
  import zoneinfo
  tz = zoneinfo.ZoneInfo("Europe/Warsaw")
  second_pass = datetime(2025, 10, 26, 2, 30, tzinfo=tz, fold=1)
  t = Time(second_pass)
  assert t.fold == 1
  assert t.timestamp() == second_pass.timestamp()
  assert t.to_datetime().fold == 1
  assert t.copy().fold == 1

def values_that_compare_equal_hash_equal():
  """Equality ran in UTC while the hash did not, so a set kept one instant twice."""
  naive = Time("2025-03-01 12:00")
  aware = Time(naive.to_datetime().astimezone(timezone.utc))
  assert naive == aware
  assert hash(naive) == hash(aware)
  assert len({naive, aware}) == 1

def a_partial_date_fails_as_a_date_not_as_a_number():
  """`2025-03` is only digits and a dash; read as a timestamp, it would fail inside `float()`."""
  with pytest.raises(ValueError, match="Cannot parse time"):
    Time("2025-03")
