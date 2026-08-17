# xaeian/eda/ee.py

"""
Standard E-series resistor values and voltage converter divider selection.

`VConv` instances (`RDIV`, `AOZ1282`, `MC34063`, `LM317`, `LM337`) give Vout for a resistor pair
and search the E-series for the pair closest to a target voltage.

Example:
  >>> R1, R2, vout = AOZ1282.find(3.3)[0]
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
  """Expand an E-series over decade multipliers, deduplicated and sorted."""
  return sorted(set(round(x * m, 2) for m in decades for x in series))

#-------------------------------------------------------------------------------------- VConv class

class VConv:
  """Voltage converter divider: call it for Vout, `.find()` for the closest R1/R2 pair."""
  def __init__(self, formula, vref:float, doc:str=""):
    self._formula = formula
    self.vref = vref
    self.__doc__ = doc

  def __call__(self, R1:float, R2:float, vref:float|None=None) -> float:
    """Vout for the `R1`/`R2` pair, `vref=None` uses the converter's own reference."""
    return self._formula(R1, R2, vref if vref is not None else self.vref)

  def __repr__(self):
    return f"<VConv vref={self.vref}>"

  def find(
    self,
    vtarget:float,
    rseries:list[float]|None = None,
    vref:float|None = None,
    tolerance:float = 0.1,
    limit:int = 5,
  ) -> list[tuple[float, float, float]]:
    """
    Find R1/R2 pairs within `tolerance` volts of `vtarget`: `(R1, R2, Vout)`, best first.

    At most `limit` pairs. `rseries=None` → `expand_series(E24)`, `vref=None` → the converter's
    own `vref`; R1 and R2 are taken from `rseries` and carry its unit.
    """
    if rseries is None:
      rseries = expand_series(E24)
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

#------------------------------------------------------------------------------ Converter instances

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