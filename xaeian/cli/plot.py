# xaeian/cli/plot.py

"""`xn plot`: a CSV file drawn as a waveform, in a window to zoom and pan."""

import sys, math
from ..log import Print
from ..colors import Color as c, grey, fmt_path, fmt_count
from ..files import PATH, FILE, CSV
from ..xstring import ensure_suffix
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
examples:
  xn plot log.csv - every column against the first, one panel per unit
  xn plot log.csv -c vin_V,vout_V - only these columns
  xn plot sweep.csv -x vin_V - another column on the x axis
  xn plot log.csv -o log.png - save instead of opening a window (.png .svg .pdf)
  xn plot log.csv --dark - dark theme
"""

#------------------------------------------------------------------------------------------- Values

def _delimiter(path:str) -> str:
  """`,`, `;` or tab, whichever the header row holds most of."""
  header = next(FILE.iter_lines(path), "")
  return max(",;\t", key=header.count)

def _numbers(cells, decimal:str) -> tuple[list[float], int]:
  """Cells → floats with `nan` for a gap, and how many filled cells were not numbers."""
  values: list[float] = []
  bad = 0
  for cell in cells:
    cell = (cell or "").strip()
    try: values.append(float(cell.replace(decimal, ".")))
    except ValueError:
      values.append(math.nan)
      if cell: bad += 1
  return values, bad

def _times(cells):
  """Cells → `datetime64` with `NaT` for a gap, `None` unless every filled cell is ISO time."""
  import numpy as np
  try: return np.array(cells, dtype="datetime64[us]")
  except ValueError: return None

#--------------------------------------------------------------------------------------------- Main

def main() -> None:
  parser = make_parser("Plot a CSV as a waveform: first column on x, one panel per unit",
    EXAMPLES)
  parser.add_argument("src", help="CSV file with a header row")
  parser.add_argument("-x", default=None, metavar="NAME",
    help="Column on the x axis (default: first)")
  parser.add_argument("-c", "--columns", default=None, metavar="LIST",
    help="Comma-separated columns to draw (default: all)")
  parser.add_argument("-o", "--output", dest="dst", default=None, metavar="PATH",
    help="Save to .png .svg .pdf instead of opening a window")
  parser.add_argument("--dark", action="store_true", help="Dark theme")
  add_help(parser)
  args = parser.parse_args()
  try:
    from ..plot import Plot
  except ImportError as e:
    p.err(f"{e}")
    sys.exit(1)
  path = ensure_suffix(args.src, ".csv")
  name = PATH.basename(path)
  if not FILE.exists(path):
    p.err(f"File {fmt_path(name, c.ORANGE)} not found")
    sys.exit(1)
  delimiter = _delimiter(path)
  # A comma that is not the delimiter is a decimal point: Excel writes `3,14` between `;`
  decimal = "." if delimiter == "," else ","
  try:
    table = CSV.load_vectors(path, delimiter=delimiter)
  except Exception as e:
    p.err(f"Failed to read {fmt_path(name, c.ORANGE)} | {e}")
    sys.exit(1)
  if not table:
    p.err(f"No rows in {fmt_path(name, c.ORANGE)}")
    sys.exit(1)
  x = args.x or next(iter(table))
  names = [col.strip() for col in args.columns.split(",")] if args.columns else list(table)
  unknown = [col for col in [x, *names] if col not in table]
  if unknown:
    p.err(f"No column {c.BLUE}{', '.join(unknown)}{c.END} in {fmt_path(name, c.ORANGE)}")
    p.gap(f"Columns: {', '.join(table)}")
    sys.exit(1)
  # Numbers first: numpy reads a column of plain integers as years
  xs, _ = _numbers(table[x], decimal)
  if all(math.isnan(v) for v in xs): xs = _times(table[x])
  if xs is None:
    p.err(f"Column {c.BLUE}{x}{c.END} holds neither numbers nor ISO times, pick another with -x")
    sys.exit(1)
  data = {x: xs}
  for col in names:
    if col == x: continue
    values, bad = _numbers(table[col], decimal)
    if all(math.isnan(v) for v in values):
      p.wrn(f"Skipped {c.BLUE}{col}{c.END} {grey('(no numbers)')}")
      continue
    if bad: p.wrn(f"{c.BLUE}{col}{c.END}: {c.CYAN}{bad}{c.END} cells not numbers, left as gaps")
    data[col] = values
  if len(data) < 2:
    p.err(f"Nothing to plot in {fmt_path(name, c.ORANGE)}")
    sys.exit(1)
  plot = Plot(theme="dark" if args.dark else "clean").columns(data, x=x).title(name)
  p.inf(f"{fmt_path(name, c.ORANGE)}: {fmt_count(len(data) - 1, 'column', color=c.CYAN)}, "
    f"{fmt_count(len(xs), 'row', color=c.CYAN)} against {c.BLUE}{x}{c.END}")
  if not args.dst:
    plot.show()
    return
  try:
    plot.save(args.dst)
  except Exception as e:
    p.err(f"Failed to save {fmt_path(args.dst)} | {e}")
    sys.exit(1)
  p.ok(f"Plotted {fmt_path(name, c.ORANGE)} → {fmt_path(PATH.basename(args.dst))}")

if __name__ == "__main__":
  main()
