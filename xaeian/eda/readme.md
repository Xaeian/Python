# `xaeian.eda`

Electronics tooling. Requires `pip install xaeian[eda]`.

## `ee`: E-series and voltage converters

```py
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

## `kicad`: Production file generator

Automates BOM, gerber, CPL, PDF export via `kicad-cli`.

```py
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

```py
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

## `spice`: NgSpice simulation runner

Template-based netlist substitution, batch execution, output parsing, CSV caching, parallel parametric sweeps.
```py
from xaeian.eda.spice import Simulation

sim = Simulation("inverter", lib="C:/Kicad/Spice",
  params={"RLOAD": "1k"},
  rename={"V(OUT)": "vout", "I(VCC)": "icc"},
  scale={"icc": 1000},  # A → mA
)

# Single run
data = sim.run(RLOAD="2.2k")
data["vout"]   # [0.0, 0.12, 0.48, ...]
data["TIME"]   # [0.0, 1e-4, 2e-4, ...]

# Parametric sweep (parallel, cached)
results = sim.sweep(RLOAD=["1k", "2.2k", "4.7k", "10k"])
results["2.2k"]["vout"]  # [0.0, 0.12, ...]

# Plot with family()
from xaeian.plot import Plot
(Plot(theme="dark")
  .family(results, "TIME", "vout", "R={key}")
  .hline(3.3, label="VIH", color="#EE6677", ls="--")
  .ylabel("Output [V]")
  .title("Inverter — Load Sweep")
  .show())
```

### Standalone parser
```py
from xaeian.eda.spice import parse_output

data = parse_output("result.out")  # nutmeg or wrdata format
```

### Template convention

Circuit file `inverter.cir` with placeholders:
```spice
* Inverter
.include "{LIB}/models/2n2222.lib"
R1 vcc out {RLOAD}
...
```

Simulation commands in `inverter.sp`:
```spice
.tran 1u 10m
.control
run
wrdata {FILE} v(out) i(vcc)
.endc
.end
```

`{LIB}` → `lib=` parameter, `{RLOAD}` → `params=` or `run()`/`sweep()` kwargs, `{FILE}` → auto-generated output path.