# xaeian/eda/ee.py

"""
Electronics helpers — E-series and voltage converter resistor selection.

Constants:
  `E6`, `E12`, `E24` — standard resistor value series

Functions:
  `expand_series` — expand series across decades

Classes:
  `VConv` — voltage converter resistor divider formulas and finder

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

#----------------------------------------------------------------------------- VConv class

class VConv:
  """Voltage converter resistor divider formulas and finder."""

  @staticmethod
  def RDIV(R1:float, R2:float, vref:float=3.3) -> float:
    """Generic resistor divider: `Vout = Vref * R1 / (R1 + R2)`"""
    return vref * (R1 / (R1 + R2))

  @staticmethod
  def AOZ1282(R1:float, R2:float, vref:float=0.8) -> float:
    """AOZ1282 buck: `Vout = Vref * (1 + R1/R2)`"""
    return vref * (1 + (R1 / R2))

  @staticmethod
  def MC34063(R1:float, R2:float, vref:float=1.25) -> float:
    """MC34063 converter: `Vout = Vref * (1 + R2/R1)`"""
    return vref * (1 + (R2 / R1))

  @staticmethod
  def LM337(R1:float, R2:float, vref:float=1.25) -> float:
    """LM337 negative regulator."""
    return -vref * (1 + (R2 / R1)) + (100e-9 * R2)

  @staticmethod
  def LM317(R1:float, R2:float, vref:float=1.25) -> float:
    """LM317 positive regulator."""
    return vref * (1 + (R2 / R1)) + (100e-9 * R2)

  @staticmethod
  def find(
    vtarget:float,
    formula:Callable|None = None,
    rseries:list[float]|None = None,
    vref:float|None = None,
    tolerance:float = 0.1,
    limit:int = 5,
  ) -> list[tuple[float, float, float]]:
    """
    Find R1/R2 combinations closest to target voltage.

    Args:
      vtarget: Desired output voltage.
      formula: Divider formula (default: RDIV).
      rseries: Resistor values in kΩ (default: E6+E12+E24 expanded).
      vref: Reference voltage override.
      tolerance: Max voltage deviation.
      limit: Max results to return.

    Returns:
      List of `(R1_kΩ, R2_kΩ, Vout)` tuples, best match first.

    Example:
      >>> VConv.find(5.0, VConv.AOZ1282)
      [(5.6, 1.0, 5.28), (4.7, 1.0, 4.56), ...]
    """
    if formula is None: formula = VConv.RDIV
    if rseries is None:
      rseries = expand_series(sorted(set(E6 + E12 + E24)))
    results = []
    for R1 in rseries:
      for R2 in rseries:
        vout = formula(R1, R2, vref) if vref else formula(R1, R2)
        diff = abs(vout - vtarget)
        if diff <= tolerance:
          results.append((diff, R1, R2, vout))
    results.sort(key=lambda x: x[0])
    return [(R1, R2, vout) for (_, R1, R2, vout) in results[:limit]]