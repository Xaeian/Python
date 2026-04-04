# xaeian/eda/ee.py

"""
Electronics helpers: E-series and voltage converter resistor selection.

Constants:
  `E6`, `E12`, `E24`: standard resistor value series

Functions:
  `expand_series`: expand series across decades

Classes:
  `VConv`: voltage converter resistor divider formulas and finder

Example:
  >>> from xaeian.eda.ee import E24, VConv, expand_series
  >>> results = VConv.find(3.3, VConv.AOZ1282)
  >>> for R1, R2, vout in results:
  ...   print(f"R1={R1}kΩ R2={R2}kΩ → {vout:.4f}V")
"""

from typing import Callable

E6 = [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = [
  1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
  3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
]

def expand_series(
  series:list[float],
  decades:tuple[float, ...] = (1, 10),
) -> list[float]:
  """
  Expand E-series values across decades.

  Args:
    series: Base series values (e.g. E12).
    decades: Multipliers (default: 1x, 10x).

  Returns:
    Sorted list of expanded values.

  Example:
    >>> expand_series(E6, decades=(1, 10, 100))
    [1.0, 1.5, 2.2, ..., 68.0]
  """
  return sorted(set(round(x * m, 2) for m in decades for x in series))

#---------------------------------------------------------------------------------- VConv class

class VConv:
  """Voltage converter resistor divider — callable with `.find()`."""

  def __init__(self, formula, vref:float, doc:str=""):
    self._formula = formula
    self.vref = vref
    self.__doc__ = doc

  def __call__(self, R1:float, R2:float, vref:float|None=None) -> float:
    return self._formula(R1, R2, vref if vref is not None else self.vref)

  def __repr__(self):
    return f"<VConv vref={self.vref}>"

  def find(self,
    vtarget:float,
    rseries:list[float]|None = None,
    vref:float|None = None,
    tolerance:float = 0.1,
    limit:int = 5,
  ) -> list[tuple[float, float, float]]:
    """Find R1/R2 closest to target voltage.

    Returns:
      List of `(R1_kΩ, R2_kΩ, Vout)` tuples, best match first.
    """
    if rseries is None:
      rseries = expand_series(sorted(set(E6 + E12 + E24)))
    ref = vref if vref is not None else self.vref
    results = []
    for R1 in rseries:
      for R2 in rseries:
        vout = self._formula(R1, R2, ref)
        diff = abs(vout - vtarget)
        if diff <= tolerance:
          results.append((diff, R1, R2, vout))
    results.sort(key=lambda x: x[0])
    return [(R1, R2, vout) for (_, R1, R2, vout) in results[:limit]]

#-------------------------------------------------------------------------- Converter instances

RDIV = VConv(
  lambda R1, R2, vref: vref * R1 / (R1 + R2),
  vref=3.3, doc="Resistor divider: Vout = Vref * R1 / (R1 + R2)",
)
AOZ1282 = VConv(
  lambda R1, R2, vref: vref * (1 + R1 / R2),
  vref=0.8, doc="AOZ1282 buck: Vout = Vref * (1 + R1/R2)",
)
MC34063 = VConv(
  lambda R1, R2, vref: vref * (1 + R2 / R1),
  vref=1.25, doc="MC34063: Vout = Vref * (1 + R2/R1)",
)
LM317 = VConv(
  lambda R1, R2, vref: vref * (1 + R2 / R1) + 100e-9 * R2,
  vref=1.25, doc="LM317 positive regulator",
)
LM337 = VConv(
  lambda R1, R2, vref: -vref * (1 + R2 / R1) + 100e-9 * R2,
  vref=1.25, doc="LM337 negative regulator",
)