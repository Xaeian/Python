# tests/test_plot.py

"""
The fluent chain, rendered to a file.

The module's demo built a stacked dashboard and opened a window. The same chain runs here
against a headless backend and has to produce a real image.
"""

import pytest

np = pytest.importorskip("numpy", reason="plot needs the [plot] extra")
matplotlib = pytest.importorskip("matplotlib", reason="plot needs the [plot] extra")
matplotlib.use("Agg")

from xaeian.plot import Plot, quick

@pytest.fixture
def series():
  """Twelve hours of three sensors, the shape the demo used."""
  hours = np.arange(0, 12, 0.05)
  temp = 22 + 3 * np.sin(hours * 2 * np.pi / 24)
  hum = 55 + 8 * np.cos(hours * 2 * np.pi / 24)
  volts = 3.3 + 0.02 * np.sin(hours)
  return hours, temp, hum, volts

def a_single_trace_shortcut_renders(series, tmp_path):
  hours, temp, _, _ = series
  out = tmp_path / "quick.png"
  quick(hours, temp, "Temperature [°C]").save(str(out))
  assert out.exists() and out.stat().st_size > 1000

def the_stacked_dashboard_from_the_demo_renders(series, tmp_path):
  hours, temp, hum, volts = series
  out = tmp_path / "dashboard.png"
  (Plot(theme="dark", size=(14, 9))
    .line(hours, temp, "Temperature [°C]")
    .fill(hours, temp + 1, temp - 1, alpha=0.12)
    .hline(25, label="Alarm", color="#EE6677", ls="--")
    .panel()
    .line(hours, hum, "Humidity [%]")
    .twinx()
    .line(hours, volts, "Supply [V]")
    .panel(height=0.7)
    .line(hours, volts, "3.3V [V]")
    .title("Sensors")
    .save(str(out)))
  assert out.exists() and out.stat().st_size > 5000

def every_step_of_the_chain_returns_the_plot(series):
  """A fluent API that ever returns None breaks the next call in the chain."""
  hours, temp, _, _ = series
  plot = Plot()
  for step in (
    lambda p: p.line(hours, temp, "T"),
    lambda p: p.hline(25, label="Alarm"),
    lambda p: p.fill(hours, temp + 1, temp - 1),
    lambda p: p.panel(),
    lambda p: p.twinx(),
    lambda p: p.title("Sensors"),
  ):
    assert step(plot) is plot

def an_unknown_theme_falls_back_instead_of_raising():
  """Recorded, not endorsed: a typo in a theme name is accepted silently."""
  assert Plot(theme="does-not-exist") is not None
