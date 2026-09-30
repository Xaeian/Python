# tests/test_plot.py

"""
The fluent chain, rendered to a file.

The module's demo builds a stacked dashboard and opens a window.
The same chain runs here against a headless backend and has to produce a real image.
"""

import sys
import pytest

np = pytest.importorskip("numpy", reason="plot needs the [plot] extra")
matplotlib = pytest.importorskip("matplotlib", reason="plot needs the [plot] extra")
matplotlib.use("Agg")

import matplotlib.dates as mdates
from xaeian.plot import Plot, quick
from xaeian.cli import plot as xn_plot_cli

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
  """A fluent API that ever returns `None` breaks the next call in the chain."""
  hours, temp, _, _ = series
  plot = Plot()
  for step in (
    lambda p: p.line(hours, temp, "T"),
    lambda p: p.hline(25, label="Alarm"),
    lambda p: p.vline(6, label="Event"),
    lambda p: p.text(6, 25, "peak"),
    lambda p: p.fill(hours, temp + 1, temp - 1),
    lambda p: p.columns({"time_h": hours, "temp_C": temp}),
    lambda p: p.panel(),
    lambda p: p.twinx(),
    lambda p: p.title("Sensors"),
  ):
    assert step(plot) is plot

def an_unknown_theme_falls_back_instead_of_raising():
  """Recorded, not endorsed: a typo in a theme name is accepted silently."""
  assert Plot(theme="does-not-exist") is not None

def an_empty_plot_still_renders_one_axes():
  assert len(Plot().title("Nothing yet").axes) == 1

#------------------------------------------------------------------------------------------- Labels

@pytest.mark.parametrize("header, shown", [
  ("voltage_V", "voltage [V]"),
  ("load_mA", "load [mA]"),
  ("delay_ms", "delay [ms]"),
  ("supply_in_V", "supply_in [V]"),
  ("Time [s]", "Time [s]"),
  ("sensor_id", "sensor_id"),
  ("temp_max", "temp_max"),
  ("ch_1", "ch_1"),
])
def a_header_suffix_counts_only_when_it_is_a_unit(header, shown):
  assert Plot().columns({"t": [0, 1], header: [0, 1]}).axes[0].get_ylabel() == shown

def a_line_label_is_shown_as_written():
  """As suffixes, `A` and `C` are units and `B` is not: one set of phases would split two ways."""
  plot = Plot()
  for phase in "ABC": plot.line([0, 1], [0, 1], f"phase_{phase}")
  assert plot.axes[0].get_legend_handles_labels()[1] == ["phase_A", "phase_B", "phase_C"]

def a_reference_line_leaves_the_series_its_label(series):
  hours, temp, _, _ = series
  plot = Plot().line(hours, temp, "Temperature [°C]").hline(25, label="Alarm")
  assert plot.axes[0].get_ylabel() == "Temperature [°C]"

def text_is_drawn_verbatim():
  """A label splits off its unit, an annotation keeps every character."""
  plot = Plot().line([0, 1], [0, 1], "v [V]").text(0.5, 0.5, "peak [V]")
  assert plot.axes[0].texts[0].get_text() == "peak [V]"

def a_legend_takes_the_placement_it_is_given(series):
  """`loc` is the only placement matplotlib sees: a second, forced one would raise `TypeError`."""
  hours, temp, _, _ = series
  plot = Plot().line(hours, temp, "a").line(hours, temp + 1, "b").legend(loc="lower left")
  assert plot.axes[0].get_legend() is not None

#------------------------------------------------------------------------------------------ Columns

def columns_share_a_panel_per_unit(series):
  hours, temp, hum, volts = series
  table = {"time_s": hours, "vin_V": volts, "vout_V": volts - 0.1, "load_mA": hum, "U1": temp}
  axes = Plot().columns(table).axes
  assert [len(ax.get_lines()) for ax in axes] == [2, 1, 1]
  assert [ax.get_ylabel() for ax in axes] == ["[V]", "load [mA]", "U1"]
  assert axes[-1].get_xlabel() == "time [s]"

#---------------------------------------------------------------------------------------- Time axis

@pytest.fixture
def two_seconds():
  """Two seconds at 1kHz, where ticks rounded to whole seconds would repeat."""
  t = np.arange("2025-03-01T12:00:00", "2025-03-01T12:00:02", dtype="datetime64[ms]")
  return Plot().line(t, np.sin(np.arange(len(t)) / 50), "v_V"), t

def sub_second_ticks_do_not_repeat(two_seconds):
  plot, _ = two_seconds
  plot.fig.canvas.draw()
  labels = [tick.get_text() for tick in plot.axes[0].get_xticklabels()]
  assert len(labels) > 2
  assert len(set(labels)) == len(labels)

def the_cursor_reads_a_date_axis_to_the_millisecond(two_seconds):
  """The toolbar gives the full timestamp, not the tick's rounding to minutes or whole seconds."""
  plot, t = two_seconds
  readout = plot.axes[0].format_coord(mdates.date2num(t[1250]), 0)
  assert "2025-03-01 12:00:01.250" in readout

@pytest.mark.filterwarnings("ignore:.*non-interactive")
def the_window_is_named_after_the_title(series):
  hours, temp, _, _ = series
  plot = Plot().line(hours, temp, "T").title("Sensors").show()
  assert plot.fig.canvas.manager.get_window_title() == "Sensors"

#------------------------------------------------------------------------------------------ xn plot

@pytest.fixture
def xn_plot(monkeypatch):
  """`xn plot` run in-process, answering its exit code."""
  def run(*argv:str) -> int:
    monkeypatch.setattr(sys, "argv", ["xn plot", *argv])
    try: xn_plot_cli.main()
    except SystemExit as e: return int(e.code or 0)
    return 0
  return run

@pytest.fixture
def log_csv(tmp_path):
  """A `Recorder` log as `CSV.add_row` writes it, with the junk a real log collects."""
  rows = ["time,vin_V,vout_V,load_mA,state"]
  for i in range(200):
    vout = "OL" if i == 100 else f"{3.3 + 0.01 * np.sin(i / 10):.4f}"
    rows.append(f"2025-03-01 12:00:{i // 10:02}.{i % 10}00000,5.0,{vout},{120 + i % 7},RUN")
  path = tmp_path / "log.csv"
  path.write_text("\n".join(rows) + "\n", encoding="utf-8")
  return path

def xn_plot_saves_a_log_as_a_waveform(xn_plot, log_csv, tmp_path):
  out = tmp_path / "log.png"
  assert xn_plot(str(log_csv), "-o", str(out)) == 0
  assert out.stat().st_size > 5000

@pytest.mark.filterwarnings("ignore:.*non-interactive")
def xn_plot_opens_a_window_without_output(xn_plot, log_csv):
  assert xn_plot(str(log_csv)) == 0

def xn_plot_reads_semicolons_and_decimal_commas(xn_plot, tmp_path):
  """What Excel writes in a comma-decimal locale; a misread column has nothing left to draw."""
  src = tmp_path / "excel.csv"
  src.write_text("czas_s;napiecie_V\n0,0;1,5\n0,1;1,6\n0,2;1,7\n", encoding="utf-8")
  assert xn_plot(str(src), "-o", str(tmp_path / "excel.png")) == 0

def xn_plot_refuses_what_it_cannot_draw(xn_plot, log_csv, tmp_path):
  assert xn_plot(str(tmp_path / "missing.csv")) == 1  # no such file
  assert xn_plot(str(log_csv), "-x", "nope") == 1     # no such column
  assert xn_plot(str(log_csv), "-x", "state") == 1    # text on the x axis
  assert xn_plot(str(log_csv), "-c", "state") == 1    # nothing numeric left to draw
