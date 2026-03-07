# `xaeian.eda`

Electronics tooling. Requires `pip install xaeian[eda]`.

## `ee` — E-series and voltage converters

```python
from xaeian.eda.ee import E6, E12, E24, expand_series, VConv

# Expand resistor series across decades
expand_series(E12, decades=(1, 10, 100))  # [1.0, 1.2, ..., 82.0]

# Find R1/R2 for target voltage
VConv.find(3.3, VConv.AOZ1282)
# [(3.3, 1.0, 3.44), (6.8, 2.2, 3.27), ...]

VConv.find(5.0, VConv.MC34063, tolerance=0.05, limit=3)

# Formulas: RDIV, AOZ1282, MC34063, LM317, LM337
VConv.AOZ1282(5.6, 1.0)  # 5.28V
VConv.RDIV(10, 10)        # 1.65V
```

## `kicad` — Production file generator

Automates BOM, gerber, CPL, PDF export via `kicad-cli`.

```python
from xaeian.eda.kicad import KiCad

kc = KiCad("./kicad", "./produce")

kc.bom()                        # generic BOM
kc.bom("JLCPCB")               # JLCPCB format (LCSC parts)
kc.bom("EuroCircuits")          # EuroCircuits format

kc.gerber()                     # gerbers + drill → ZIP
kc.cpl()                        # pick & place CSV
kc.cpl(jlcpcb_format=True)     # JLCPCB CPL format
kc.cpl(
  blacklist=["CP", "TP"],       # skip test points, connectors
  rotation_refs={90: ["U1"]},   # rotation corrections
  dnp=["R99"],                  # do not place
)

kc.pdf_layout()                 # multi-page PCB layout PDF
kc.pdf_layout(top=True, bot=True)
kc.pdf_schema()                 # schematic PDF

kc.zip_prod("1.0.0")           # ZIP everything
kc.ok()                         # print success
```

### Typical `produce.py`

```python
from xaeian.eda.kicad import KiCad

kc = KiCad("./kicad", "./produce")
kc.pdf_schema()
kc.pdf_layout()
kc.bom()
kc.bom("JLCPCB")
kc.gerber()
kc.cpl(jlcpcb_format=True)
kc.zip_prod("1.0.0")
kc.ok()
```