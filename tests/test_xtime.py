# tests/test_xtime.py

"""Time: parsing, interval arithmetic, timezone-aware formatting, rounding."""

import pytest
from datetime import datetime, timezone, timedelta
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

def rejects_unsupported_type():
  with pytest.raises(TypeError):
    Time(["nope"])

def adds_interval_keeps_wall_clock():
  base = Time("2025-03-01 12:00:00")
  assert base + "1w" == Time("2025-03-08 12:00:00")
  assert base + "3d" == Time("2025-03-04 12:00:00")
  assert base + "90m" == Time("2025-03-01 13:30:00")

def interval_1h2ms_adds_hour_and_millis():
  # regression: "ms" must beat "m" — 1h2ms is +1h +2ms, not +1h +2min
  assert (Time("2025-03-01 12:00:00") + "1h2ms").to("%H:%M:%S.%f") == "13:00:00.002000"

def multi_token_interval_with_spaces():
  assert Time("2025-03-01 12:00") + "1d 2h" == Time("2025-03-02 14:00")
  assert Time("2025-03-01 12:00") + "-6h 30m" == Time("2025-03-01 06:30")

def fractional_time_intervals():
  base = Time("2025-03-01 12:00:00")
  assert base + "1.5h" == Time("2025-03-01 13:30:00")
  assert base + "0.5d" == Time("2025-03-02 00:00:00")

def fractional_calendar_units_truncate():
  # months/years step by whole units — the fractional part is dropped
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

def equals_equivalent_string():
  assert Time("2025-03-01 12:00:00") == "2025-03-01 12:00:00"

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
  ("s",  "2025-03-05 14:37:23"),
  ("m",  "2025-03-05 14:37:00"),
  ("h",  "2025-03-05 14:00:00"),
  ("d",  "2025-03-05 00:00:00"),
  ("mo", "2025-03-01 00:00:00"),
  ("y",  "2025-01-01 00:00:00"),
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
  assert time_to("2025-03-01T12:00:00+00:00", "ts") == datetime(2025, 3, 1, 12, tzinfo=timezone.utc).timestamp()
