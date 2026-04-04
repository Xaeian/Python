# xaeian/eda/__init__.py

"""Electronics — E-series, voltage converters, KiCad tooling, NgSpice runner."""

from .ee import E6, E12, E24, expand_series, VConv
from .spice import Simulation, parse_output
from .kicad_clean import clean_step, clean_footprint

__extras__ = ("eda", ["sexpdata", "pypdf", "PyMuPDF"])

__all__ = [
  "E6", "E12", "E24", "expand_series", "VConv",
  "Simulation", "parse_output",
  "clean_step", "clean_footprint"
]

try:
  from .kicad import KiCad
  __all__ += ["KiCad"]
except ImportError:
  pass