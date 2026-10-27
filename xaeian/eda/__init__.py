# xaeian/eda/__init__.py

"""Electronics - E-series, voltage converters, KiCad production exports, ngspice runner."""

from ..extras import MissingExtra
from .ee import E6, E12, E24, expand_series, VConv
from .spice import Simulation, parse_output

__extras__ = ("eda", ["sexpdata", "pypdf", "PyMuPDF"])

__all__ = [
  "E6", "E12", "E24", "expand_series", "VConv",
  "Simulation", "parse_output",
]

# KiCad needs `sexpdata`, so it joins the public API only when the extra is installed
try:
  from .kicad import KiCad
  __all__ += ["KiCad"]
except MissingExtra:
  pass