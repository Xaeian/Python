# xaeian/plot.py

"""
Minimal fluent matplotlib wrapper for CLI time-series plotting.

Traces are stored as dicts, the figure is built on `show()`/`save()`. Stacked panels share the
x-axis, datetime axes format themselves, `.fig`/`.axes` escape to raw matplotlib.

Requires: `pip install xaeian[plot]`

Example:
  >>> (Plot(theme="dark")
  ...   .line(t, temp, "Temperature [°C]")
  ...   .panel(height=0.5)
  ...   .line(t, volt, "Voltage [V]")
  ...   .title("Sensor Dashboard")
  ...   .save("dashboard.png"))
"""

from __future__ import annotations

__extras__ = ("plot", ["matplotlib", "numpy"])

import os
from datetime import datetime, date

try:
  import matplotlib
  import matplotlib.pyplot as plt
  import matplotlib.dates as mdates
  import matplotlib.ticker
  import numpy as np
except ImportError as e:
  raise ImportError("Install with: pip install xaeian[plot]  (matplotlib + numpy)") from e

#------------------------------------------------------------------------------------------ Helpers

# Paul Tol colorblind-safe: bright (1-7), vibrant (8-10), muted (11-20)
PALETTE = [
  "#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE",
  "#AA3377", "#BBBBBB", "#332288", "#882255", "#117733",
  "#44AA99", "#EE8866", "#CC6677", "#DDCC77", "#999933",
  "#6699CC", "#661100", "#004488", "#AA4499", "#EEDD88",
]

def _parse_label(label:str|tuple|None) -> tuple[str, str]:
  """Parse `"Name [unit]"` or `("Name", "unit")` → `(name, unit)`."""
  if label is None: return ("", "")
  if isinstance(label, (list, tuple)):
    if not label: return ("", "")
    return (str(label[0]), str(label[1]) if len(label) > 1 else "")
  s = str(label)
  i = s.rfind("[")
  if i > 0 and s.endswith("]"):
    return (s[:i].strip(), s[i+1:-1].strip())
  return (s, "")

def _fmt_label(name:str, unit:str) -> str:
  """`"Temperature"` + `"°C"` → `"Temperature [°C]"`."""
  return f"{name} [{unit}]" if unit else name

def _is_datetime(x) -> bool:
  """True for datetime-like scalars, sequences and ndarrays."""
  if x is None: return False
  if isinstance(x, (datetime, date, np.datetime64)): return True
  if isinstance(x, np.ndarray): return np.issubdtype(x.dtype, np.datetime64)
  if not hasattr(x, "__len__") or not len(x): return False
  v = x[0] if hasattr(x, "__getitem__") else next(iter(x), None)
  return isinstance(v, (datetime, date, np.datetime64))

#----------------------------------------------------------------------------------- Date formatter

class _SmartDateFormatter(matplotlib.ticker.Formatter):
  """
  Tick format chosen from the visible time span.

  < 10 min → `16:30:15`
  < 24 h → `16:30`
  1-60 d → `16:30`, with `25-03-01` on a second line under the first tick of each day
  60 d-2 y → `25-03-01`
  > 2 y → `2025-03`
  """
  def __call__(self, x, pos=None):
    dt = mdates.num2date(x)
    span = abs(self.axis.get_view_interval()[1]
      - self.axis.get_view_interval()[0]) # span in days
    if span >= 365 * 2: return dt.strftime("%Y-%m")
    if span >= 60: return dt.strftime("%y-%m-%d")
    if span < 10 / 60 / 24: return dt.strftime("%H:%M:%S")
    if span < 1.0: return dt.strftime("%H:%M")
    locs = self.axis.get_majorticklocs()
    is_first = (pos == 0) or (len(locs) < 2)
    prev_date = None
    if not is_first and pos and pos <= len(locs):
      prev_date = mdates.num2date(locs[pos - 1]).date()
    if is_first or prev_date != dt.date():
      return dt.strftime("%H:%M\n%y-%m-%d")
    return dt.strftime("%H:%M")

def _setup_date_axis(ax):
  loc = mdates.AutoDateLocator()
  ax.xaxis.set_major_locator(loc)
  ax.xaxis.set_major_formatter(_SmartDateFormatter())

#------------------------------------------------------------------------------------------- Themes

_COMMON = {
  "axes.grid": True,
  "axes.spines.top": False,
  "axes.spines.right": False,
  "legend.frameon": True,
  "legend.fancybox": True,
  "legend.framealpha": 0.88, # data peeks through
  "legend.fontsize": 9,
  "axes.labelsize": 10,
  "axes.labelpad": 6, # ylabel ↔ axis gap (pt)
  "axes.titlesize": 11,
  "xtick.labelsize": 9,
  "ytick.labelsize": 9,
  "xtick.major.pad": 4, # tick label ↔ axis gap (pt)
  "ytick.major.pad": 4,
  "lines.linewidth": 1.5,
  "savefig.bbox": "tight",
  "savefig.pad_inches": 0.05,
  "pdf.fonttype": 42, # TrueType in PDFs (journals require it)
  "axes.prop_cycle": plt.cycler("color", PALETTE),
}

THEMES = {
  "clean": {**_COMMON,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#cccccc",
    "grid.color": "#e0e0e0", "grid.alpha": 0.7, "grid.linewidth": 0.6,
    "legend.edgecolor": "#cccccc",
    "xtick.color": "#555555", "ytick.color": "#555555",
    "axes.labelcolor": "#333333", "text.color": "#333333",
  },
  "dark": {**_COMMON,
    "figure.facecolor": "#1e1e1e",
    "axes.facecolor": "#252525",
    "axes.edgecolor": "#444444",
    "grid.color": "#333333", "grid.alpha": 0.8, "grid.linewidth": 0.5,
    "legend.edgecolor": "#555555",
    "xtick.color": "#aaaaaa", "ytick.color": "#aaaaaa",
    "axes.labelcolor": "#cccccc", "text.color": "#cccccc",
    "savefig.facecolor": "#1e1e1e",
  },
}

#--------------------------------------------------------------------------------------------- Plot

class Plot:
  """
  Fluent matplotlib wrapper with deferred rendering.

  Args:
    theme: `"clean"` or `"dark"`.
    size: `(width, height)` in inches.
    dpi: display only, save DPI comes from `save(dpi=)`.
  """
  def __init__(self, theme:str="clean", size:tuple=(14, 7), dpi:int=100):
    self._theme = theme
    self._size = size
    self._dpi = dpi
    self._title: str|None = None
    self._xlabel: str|None = None
    self._panels: list[dict] = []
    self._cur: dict = self._empty_panel()
    self._fig: plt.Figure|None = None
    self._axes: list[plt.Axes] = []
    self._rendered = False

  #------------------------------------------------------------------------------- Panel management

  @staticmethod
  def _empty_panel() -> dict:
    return {
      "traces": [], "ylabel": None, "height": 1.0,
      "xlim": None, "ylim": None,
      "logx": False, "logy": False,
      "grid": None, "legend": None,
      "twin": None, # when set: dict of traces/ylabel/ylim/logy
    }

  @property
  def _target(self) -> dict:
    """Twin if active, else the main panel."""
    return self._cur["twin"] if self._cur["twin"] is not None else self._cur

  def panel(self, height:float=1.0) -> Plot:
    """Finalize current panel, start new subplot below. `height` is a ratio between panels."""
    self._panels.append(self._cur)
    self._cur = self._empty_panel()
    self._cur["height"] = height
    return self

  def twinx(self) -> Plot:
    """Start twin Y axis on current panel. Subsequent traces go to twin."""
    if self._cur["twin"] is None:
      self._cur["twin"] = {
        "traces": [], "ylabel": None, "ylim": None, "logy": False,
      }
    return self

  #---------------------------------------------------------------------------------- Trace methods

  def _add(self, kind:str, x, y, label, kw) -> Plot:
    name, unit = _parse_label(label)
    self._target["traces"].append(
      {"kind": kind, "x": x, "y": y, "name": name, "unit": unit, "kw": kw}
    )
    return self

  def line(self, x, y, label:str|tuple|None=None, **kw) -> Plot:
    """Line trace. `**kw` → `ax.plot()`."""
    return self._add("line", x, y, label, kw)

  def scatter(self, x, y, label:str|tuple|None=None, **kw) -> Plot:
    """Scatter trace. `**kw` → `ax.scatter()`."""
    return self._add("scatter", x, y, label, kw)

  def step(self, x, y, label:str|tuple|None=None, where:str="post", **kw) -> Plot:
    """Step trace: digital signals, FSM states."""
    kw["where"] = where
    return self._add("step", x, y, label, kw)

  def bar(self, x, y, label:str|tuple|None=None, **kw) -> Plot:
    """Bar trace. `**kw` → `ax.bar()`."""
    return self._add("bar", x, y, label, kw)

  def fill(self, x, y1, y2=0, label:str|tuple|None=None, alpha:float=0.3, **kw) -> Plot:
    """Filled region between y1 and y2: confidence bands, envelopes."""
    kw["alpha"] = alpha
    name, unit = _parse_label(label)
    self._target["traces"].append(
      {"kind": "fill", "x": x, "y": y1, "y2": y2, "name": name, "unit": unit, "kw": kw}
    )
    return self

  def family(self, data:dict, x:str, y:str, fmt:str="{key}", **kw) -> Plot:
    """
    Plot family of curves from sweep/parametric results.

    Args:
      data: label → dict of column arrays, as returned by `Simulation.sweep()`.
      x, y: column keys inside each result dict.
      fmt: label template, `{key}` is the outer dict key.

    Example:
      >>> results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k"])
      >>> Plot().family(results, "TIME", "V(OUT)", "R={key}").show()
    """
    for key, d in data.items():
      self.line(d[x], d[y], fmt.format(key=key), **kw)
    return self

  def hline(self, y:float, label:str|None=None, **kw) -> Plot:
    """Horizontal reference line: threshold, alarm level."""
    kw.setdefault("ls", "--")
    kw.setdefault("alpha", 0.7)
    kw.setdefault("lw", 1.0)
    name, unit = _parse_label(label)
    # reference lines land on the main panel even while a twin is active
    self._cur["traces"].append(
      {"kind": "hline", "x": None, "y": y, "name": name, "unit": unit, "kw": kw}
    )
    return self

  def vline(self, x, label:str|None=None, **kw) -> Plot:
    """Vertical reference line: event marker, timestamp."""
    kw.setdefault("ls", "--")
    kw.setdefault("alpha", 0.7)
    kw.setdefault("lw", 1.0)
    name, unit = _parse_label(label)
    self._cur["traces"].append(
      {"kind": "vline", "x": x, "y": None, "name": name, "unit": unit, "kw": kw}
    )
    return self

  def text(self, x, y, s:str, **kw) -> Plot:
    """Text annotation at `(x, y)`."""
    kw.setdefault("fontsize", 9)
    self._cur["traces"].append(
      {"kind": "text", "x": x, "y": y, "name": s, "unit": "", "kw": kw}
    )
    return self

  #---------------------------------------------------------------------------------- Configuration

  def title(self, text:str) -> Plot:
    """Figure suptitle (above all panels)."""
    self._title = text
    return self

  def xlabel(self, text:str) -> Plot:
    """X-axis label (applied to bottom panel only)."""
    self._xlabel = text
    return self

  def ylabel(self, text:str) -> Plot:
    """Y-axis label for current panel (or twin if active)."""
    self._target["ylabel"] = text
    return self

  def xlim(self, lo=None, hi=None) -> Plot:
    """X-axis range. Pass `None` for auto on either end."""
    self._cur["xlim"] = (lo, hi)
    return self

  def ylim(self, lo=None, hi=None) -> Plot:
    """Y-axis range for current panel (or twin)."""
    self._target["ylim"] = (lo, hi)
    return self

  def logx(self) -> Plot:
    """Log scale on x-axis."""
    self._cur["logx"] = True
    return self

  def logy(self) -> Plot:
    """Log scale on y-axis (or twin)."""
    self._target["logy"] = True
    return self

  def grid(self, show:bool=True) -> Plot:
    """Override grid visibility for current panel."""
    self._cur["grid"] = show
    return self

  def legend(self, show:bool=True, **kw) -> Plot:
    """Override legend. `show=False` hides it. `**kw` → `ax.legend()`."""
    self._cur["legend"] = (show, kw)
    return self

  def size(self, w:float, h:float) -> Plot:
    """Override figure size in inches."""
    self._size = (w, h)
    return self

  #-------------------------------------------------------------------------------------- Rendering

  def _finalize_panels(self) -> list[dict]:
    """Panels holding traces, the unfinished current one included."""
    panels = self._panels + [self._cur]
    return [p for p in panels if p["traces"] or (p["twin"] and p["twin"]["traces"])]

  def _render(self):
    """Build the figure from stored specs, once, on `show()`/`save()`/`.fig`/`.axes`."""
    if self._rendered: return
    panels = self._finalize_panels()
    if not panels:
      style = THEMES.get(self._theme, THEMES["clean"])
      with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=self._size, dpi=self._dpi)
      if self._title: fig.suptitle(self._title, fontsize=12, fontweight="bold")
      if self._xlabel: ax.set_xlabel(self._xlabel)
      self._fig, self._axes = fig, [ax]
      self._rendered = True
      return
    n = len(panels)
    ratios = [p["height"] for p in panels]
    style = THEMES.get(self._theme, THEMES["clean"])
    with plt.rc_context(style):
      fig, axarr = plt.subplots(
        n, 1, figsize=self._size, dpi=self._dpi,
        sharex=(n > 1), squeeze=False,
        gridspec_kw={"height_ratios": ratios, "hspace": 0.06 if n > 1 else 0.2},
        layout="constrained",
      )
      # w_pad/h_pad in inches, so /72 reads as points
      fig.get_layout_engine().set(
        w_pad=7/72, h_pad=7/72, wspace=0.02, hspace=0.06,
      )
      axes = [axarr[i, 0] for i in range(n)]
      color_idx = 0
      for pi, (panel, ax) in enumerate(zip(panels, axes)):
        is_last = (pi == n - 1)
        color_idx = self._draw_traces(ax, panel, color_idx)
        if panel["twin"] and panel["twin"]["traces"]:
          tax = ax.twinx()
          tax.spines["right"].set_visible(True) # theme hides it
          color_idx = self._draw_traces(tax, panel["twin"], color_idx)
          self._apply_axis(tax, panel["twin"], is_twin=True)
          # twin draws on top, so the merged legend has to live on it
          self._apply_legend(ax, panel, merge_from=tax)
        else:
          self._apply_legend(ax, panel)
        self._apply_axis(ax, panel)
        if panel["grid"] is not None: ax.grid(panel["grid"])
        all_traces = panel["traces"]
        if panel["twin"]:
          all_traces = all_traces + panel["twin"]["traces"]
        for tr in all_traces:
          if tr["x"] is not None and _is_datetime(tr["x"]):
            _setup_date_axis(ax)
            break
        # shared x: only the bottom panel keeps tick labels
        if not is_last and n > 1:
          ax.tick_params(labelbottom=False)
          ax.set_xlabel("")
      if self._xlabel: axes[-1].set_xlabel(self._xlabel)
      if self._title: fig.suptitle(self._title, fontsize=12, fontweight="bold")
      if n > 1: fig.align_ylabels(axes)
    self._fig, self._axes, self._rendered = fig, axes, True

  def _apply_legend(self, ax, panel:dict, merge_from=None):
    """Place legend on axis. With `merge_from`: combine handles from twin."""
    show, lkw = True, {}
    if panel["legend"] is not None: show, lkw = panel["legend"]
    if merge_from:
      h1, l1 = ax.get_legend_handles_labels()
      h2, l2 = merge_from.get_legend_handles_labels()
      if (h1 or h2) and show:
        merge_from.legend(h1 + h2, l1 + l2, loc="best", **lkw)
        leg = ax.get_legend()
        if leg: leg.remove()
    else:
      h, _ = ax.get_legend_handles_labels()
      if not h: return
      if show: ax.legend(loc="best", **lkw)
      else:
        leg = ax.get_legend()
        if leg: leg.remove()

  def _draw_traces(self, ax:plt.Axes, panel:dict, color_idx:int) -> int:
    """Draw traces, return the palette index to continue from."""
    for tr in panel["traces"]:
      kind = tr["kind"]
      kw = tr["kw"].copy()
      label = _fmt_label(tr["name"], tr["unit"]) if tr["name"] else None
      if label: kw["label"] = label
      if kind in ("line", "scatter", "step", "fill", "bar"):
        if "color" not in kw and "c" not in kw:
          kw["color"] = PALETTE[color_idx % len(PALETTE)]
          tr["kw"]["color"] = kw["color"] # persist for `_apply_axis`
        color_idx += 1
      if kind == "line": ax.plot(tr["x"], tr["y"], **kw)
      elif kind == "scatter":
        c = kw.pop("color", None)
        if c: kw["c"] = c # scatter uses `c` not `color`
        ax.scatter(tr["x"], tr["y"], **kw)
      elif kind == "step":
        ax.step(tr["x"], tr["y"], where=kw.pop("where", "post"), **kw)
      elif kind == "bar": ax.bar(tr["x"], tr["y"], **kw)
      elif kind == "fill": ax.fill_between(tr["x"], tr["y"], tr.get("y2", 0), **kw)
      elif kind == "hline": ax.axhline(tr["y"], **kw)
      elif kind == "vline": ax.axvline(tr["x"], **kw)
      elif kind == "text":
        kw.pop("label", None)
        ax.annotate(tr["name"], (tr["x"], tr["y"]), **kw)
    return color_idx

  def _apply_axis(self, ax:plt.Axes, panel:dict, is_twin:bool=False):
    """Set ylabel, limits and log scale. `is_twin` skips x config: the twin shares that axis."""
    ylabel = panel.get("ylabel")
    # lone series → derive the ylabel from it and color it to match
    if ylabel is None and len(panel["traces"]) == 1:
      t = panel["traces"][0]
      if t["name"] and t["kind"] not in ("hline", "vline", "text"):
        ylabel = _fmt_label(t["name"], t["unit"])
        color = t["kw"].get("color") or t["kw"].get("c")
        if color:
          ax.set_ylabel(ylabel, color=color)
          ax.tick_params(axis="y", colors=color)
          ylabel = None # already set with color
    if ylabel: ax.set_ylabel(ylabel)
    ylim = panel.get("ylim")
    if ylim:
      lo, hi = ylim
      if lo is not None and hi is not None: ax.set_ylim(lo, hi)
      elif lo is not None: ax.set_ylim(bottom=lo)
      elif hi is not None: ax.set_ylim(top=hi)
    if not is_twin:
      xlim = panel.get("xlim")
      if xlim:
        lo, hi = xlim
        if lo is not None and hi is not None: ax.set_xlim(lo, hi)
        elif lo is not None: ax.set_xlim(left=lo)
        elif hi is not None: ax.set_xlim(right=hi)
    if panel.get("logy"): ax.set_yscale("log")
    if not is_twin and panel.get("logx"): ax.set_xscale("log")

  #-------------------------------------------------------------------------------------- Terminals

  def show(self) -> Plot:
    """Render and display, blocks until the window is closed."""
    self._render()
    plt.show()
    return self

  def save(self, path:str, dpi:int=150, **kw) -> Plot:
    """Save to file; parent dirs created, DPI ignored for vector formats (.pdf, .svg, .eps)."""
    self._render()
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".pdf", ".svg", ".eps"): kw.setdefault("dpi", dpi)
    kw.setdefault("bbox_inches", "tight")
    kw.setdefault("facecolor", self._fig.get_facecolor())
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    self._fig.savefig(path, **kw)
    return self

  def close(self):
    """Close the figure and free its memory. Idempotent."""
    if self._fig:
      plt.close(self._fig)
      self._fig = None
      self._axes = []
      self._rendered = False

  #--------------------------------------------------------------------------------- Escape hatches

  @property
  def fig(self) -> plt.Figure:
    """Raw matplotlib Figure, renders on first access."""
    self._render()
    return self._fig

  @property
  def axes(self) -> list[plt.Axes]:
    """One raw matplotlib Axes per panel, top to bottom."""
    self._render()
    return self._axes

  #---------------------------------------------------------------------------------------- Special

  def __repr__(self):
    panels = self._finalize_panels()
    n = sum(len(p["traces"]) + (len(p["twin"]["traces"]) if p.get("twin") else 0)
      for p in panels)
    return f"<Plot {len(panels)} panels, {n} traces>"

  def __del__(self):
    self.close()

#-------------------------------------------------------------------------------------- Convenience

def quick(x, y, label:str|tuple|None=None, **kw) -> Plot:
  """Single-trace shortcut: `quick(x, y, "Data [V]").show()`."""
  return Plot().line(x, y, label, **kw)

#--------------------------------------------------------------------------------------------- Demo

def demo():
  """Stacked sensor dashboard: alarm, twinx, multi-series, datetime."""
  t = np.arange("2025-03-01", "2025-03-02", dtype="datetime64[5m]")
  n = len(t)
  hours = np.arange(n) / 12
  temp = 21 + 4 * np.sin(hours * 2 * np.pi / 24) + 0.3 * np.random.randn(n)
  hum = 55 + 20 * np.cos(hours * 2 * np.pi / 24) + np.random.randn(n)
  v33 = 3.3 + 0.05 * np.random.randn(n)
  v50 = 5.0 + 0.08 * np.random.randn(n)
  v12 = 12.0 + 0.15 * np.random.randn(n)
  sig = -70 + 10 * np.sin(hours * 2 * np.pi / 12) + 2 * np.random.randn(n)
  (Plot(theme="dark", size=(14, 9))
    .line(t, temp, "Temperature [°C]")
    .fill(t, temp + 1, temp - 1, alpha=0.12)
    .hline(25, label="Alarm", color="#EE6677", ls="--")
    .panel()
    .line(t, hum, "Humidity [%]")
    .twinx()
    .line(t, sig, "Signal [dBm]")
    .panel(height=0.7)
    .line(t, v33, "3.3V [V]")
    .line(t, v50, "5.0V [V]")
    .line(t, v12, "12V [V]")
    .ylabel("Voltage [V]")
    .title("Sensor Dashboard: 24h")
    .show())

def demo_family():
  """Family of curves: simulated parametric sweep."""
  t = np.linspace(0, 1e-3, 200)
  # same shape `Simulation.sweep()` returns
  results = {}
  for r in ["1k", "2.2k", "4.7k", "10k"]:
    rv = float(r.replace("k", "")) * 1e3
    tau = rv * 100e-9
    results[r] = {
      "TIME": t,
      "V(OUT)": 5.0 * (1 - np.exp(-t / tau)),
    }
  (Plot(theme="dark")
    .family(results, "TIME", "V(OUT)", "R = {key}")
    .hline(3.3, label="Logic high", color="#EE6677", ls="--")
    .xlabel("Time [s]")
    .ylabel("Output [V]")
    .title("RC Step Response: Parametric Sweep")
    .show())

if __name__ == "__main__":
  import sys
  if "family" in sys.argv:
    demo_family()
  else:
    demo()