
# xaeian/eda/__init__.py

"""Electronics submodule — E-series, voltage converters, KiCad tooling."""

from .ee import E6, E12, E24, expand_series, VConv

__extras__ = {"eda": ["sexpdata", "pypdf", "PyMuPDF"]}

__all__ = [
  "E6", "E12", "E24", "expand_series", "VConv",
]

try:
  from .kicad import KiCad
  __all__ += ["KiCad"]
except Exception:
  pass
