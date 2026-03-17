# xaeian/eda/kicad.py

"""
KiCad production file generator.

Automates BOM, gerber, CPL and PDF layout export via `kicad-cli`.

Example:
  >>> from xaeian.eda.kicad import KiCad
  >>> kc = KiCad("./", "./produce")
  >>> kc.bom()
  >>> kc.bom("JLCPCB")
  >>> kc.gerber()
  >>> kc.cpl(jlcpcb_format=True)
  >>> kc.pdf_layout()
  >>> kc.pdf_schema()
  >>> kc.zip_prod("v1.0")
  >>> kc.ok()
"""

import sys, re
try:
  from sexpdata import loads
except ImportError:
  raise ImportError("Install with: pip install xaeian[eda]")

from typing import Literal
from ..files import FILE, DIR, CSV, PATH
from ..colors import Color as c
from ..log import Print
from ..cmd import run as cmd_run
from ..table import (
  where, select, exclude, rename, add_column,
  set_defaults, aggregate, replace_values,
)

p = Print()

#----------------------------------------------------------------------------- KiCad class

class KiCad:
  """KiCad production file generator."""

  @staticmethod
  def load_netlist(path:str) -> list[dict]:
    """Parse KiCad netlist (.net) into list of component dicts."""
    def _tagged(x, tag):
      return isinstance(x, list) and len(x) > 0 and str(x[0]) == tag
    with open(path, "r", encoding="utf-8") as f:
      content = f.read()
    items = loads(content)
    components = []
    for item in items:
      if not _tagged(item, "components"): continue
      for comp in item[1:]:
        if not _tagged(comp, "comp"): continue
        d = {}
        for el in comp[1:]:
          if _tagged(el, "ref"): d["Reference"] = el[1]
          elif _tagged(el, "value"): d["Value"] = el[1]
          elif _tagged(el, "footprint"): d["Pacage"] = el[1]
          elif _tagged(el, "datasheet"): d["Datasheet"] = el[1]
          elif _tagged(el, "description"): d["Description"] = el[1]
          elif _tagged(el, "property") and len(el) >= 2:
            name, value = None, None
            for sub in el[1:]:
              if _tagged(sub, "name"): name = sub[1]
              elif _tagged(sub, "value"): value = sub[1]
            if name == "dnp":
              d["DNP"] = True
            elif name:
              if value: d[str(name)] = value
              else: value = ""
        set_defaults([d],
          DNP=False, Count=1, Datasheet="",
          Manufacturer="", Code="",
          LCSC="", DigiKey="", Farnell="", Mouser="", TME="",
        )
        components.append(d)
    return components

  @staticmethod
  def _fix_path(path:str) -> str:
    return path.replace("\\", "/").removesuffix("/") + "/"

  @staticmethod
  def _execute(args:list[str]):
    result = cmd_run(args)
    if result.returncode:
      for line in result.stderr.strip().splitlines():
        p.err(line)
      sys.exit(1)
    for line in result.stdout.strip().splitlines():
      p.inf(line)

  def netlist(self):
    net_name = self.project_path + self.name + ".net"
    KiCad._execute([
      "kicad-cli", "sch", "export", "netlist",
      self.sch, "--output", net_name,
    ])

  def __init__(self, project_path:str="./", produce_path:str="./produce"):
    self.project_path:str = self._fix_path(project_path)
    self.produce_path:str = self._fix_path(produce_path)
    DIR.ensure(self.produce_path)
    files = DIR.file_list(
      self.project_path, exts=[".kicad_sch"], basename=True,
    )
    if not files:
      raise FileNotFoundError(
        "No '.kicad_sch' file found in " + self.project_path
      )
    self.name:str = PATH.stem(files[0])
    self.pcb = self.project_path + self.name + ".kicad_pcb"
    self.sch = self.project_path + self.name + ".kicad_sch"
    self.netlist()
    components = KiCad.load_netlist(
      self.project_path + self.name + ".net"
    )
    # Filter out empty codes and DNP
    rows = where(components, lambda r:
      str(r.get("Code", "")).strip().lower() not in ("", "-")
    )
    rows = where(rows, lambda r: not r.get("DNP", False))
    rows = exclude(rows, "DNP")
    # Group by manufacturer + code
    self.rows:list[dict] = aggregate(rows, ["Manufacturer", "Code"], {
      "Value": "first", "Pacage": "first", "Description": "first",
      "LCSC": "first", "DigiKey": "first", "Farnell": "first",
      "Mouser": "first", "TME": "first", "Datasheet": "first",
      "Count": "sum", "Reference": "join",
    })

  def _save_csv(self, rows:list[dict], suffix:str=""):
    if suffix: suffix = f"-{suffix}"
    path = self.produce_path + self.name + suffix + ".csv"
    CSV.save(path, rows)

  def bom(
    self,
    contractor:Literal["", "JLCPCB", "EuroCircuits"] = "",
    suffix:str = "",
  ):
    """Generate BOM CSV, optionally formatted for a contractor."""
    tag = re.sub(r"[^a-z0-9]", "", contractor.lower())
    rows = [dict(r) for r in self.rows]  # shallow copy
    if tag == "jlcpcb":
      add_column(rows, "Comment", lambda r:
        f'{r["Manufacturer"]}; {r["Code"]}; {r["Description"]}'
      )
      rows = select(rows, "Comment", "Reference", "Pacage", "LCSC")
      rows = rename(rows, {
        "Reference": "Designator",
        "Pacage": "Footprint",
        "LCSC": "JLCPCB Part #",
      })
      if not suffix: suffix = "jlcpcb-bom"
    elif tag == "eurocircuits":
      add_column(rows, "Device", lambda r:
        f'{r["Manufacturer"]} — {r["Code"]}'
      )
      rows = select(rows,
        "Count", "Value", "Reference", "Device", "Pacage",
        "Description", "DigiKey", "Farnell", "Mouser", "TME",
      )
      if not suffix: suffix = "eurocir-bom"
    else:
      has_lcsc = any(
        str(r.get("LCSC", "")).strip() for r in rows
      )
      cols = [
        "Manufacturer", "Code", "Value", "Pacage",
        "Description", "Count", "Datasheet", "Reference",
      ] + (["LCSC"] if has_lcsc else [])
      rows = select(rows, *cols)
      if not suffix: suffix = "bom"
    self._save_csv(rows, suffix)

  def gerber(self):
    """Export gerber + drill files and package as ZIP."""
    gerbers_path = self.produce_path + "gerber"
    KiCad._execute([
      "kicad-cli", "pcb", "export", "gerbers", self.pcb,
      "--output", gerbers_path,
      "--layers",
      "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
      "--sdnp", "--subtract-soldermask",
      "--use-drill-file-origin", "--precision", "6",
    ])
    KiCad._execute([
      "kicad-cli", "pcb", "export", "drill", self.pcb,
      "--output", gerbers_path,
      "--format", "excellon",
      "--drill-origin", "plot",
      "--excellon-zeros-format", "decimal",
      "--excellon-units", "mm",
      "--excellon-min-header",
      "--generate-map",
      "--map-format", "gerberx2",
      "--gerber-precision", "6",
    ])
    DIR.zip(gerbers_path, self.produce_path + self.name + "-gerber.zip")
    DIR.remove(gerbers_path)

  def pdf_page(
    self, name:str, layers:list[str],
    desc:str="", desc_color:tuple=(0, 0, 0), drill:bool=True,
  ):
    """Export single PDF page from PCB layers."""
    pdf_name = f"./{self.name}-{name}.pdf"
    KiCad._execute([
      "kicad-cli", "pcb", "export", "pdf", self.pcb,
      "--output", pdf_name,
      "--layers", ",".join(layers),
      "--subtract-soldermask",
      "--drill-shape-opt", "2" if drill else "0",
      "--include-border-title",
    ])
    if desc:
      try:
        from ..mf.pdf import pdf_add_text
      except ImportError:
        raise ImportError("Install with: pip install xaeian[eda]")
      pdf_add_text(
        pdf_name, pdf_name, desc,
        (33, 20), "cobo", 10, desc_color, inplace=True,
      )
    self.pdf_pages.append(pdf_name)

  def pdf_layout(self, top:bool=True, bot:bool=False):
    """Generate multi-page PCB layout PDF."""
    self.pdf_pages = []
    grey = (0.69, 0.69, 0.69)
    if top:
      self.pdf_page("el-top",
        ["User.Drawings", "F.Fab", "Edge.Cuts"],
        "TOP Component", grey)
    if bot:
      self.pdf_page("el-bot",
        ["User.Drawings", "B.Fab", "Edge.Cuts"],
        "BOT Component", grey)
    self.pdf_page("cu-top",
      ["User.Drawings", "F.Cu", "F.Paste", "F.Mask", "Edge.Cuts"],
      "TOP Copper", (0.79, 0.20, 0.20))
    self.pdf_page("cu-bot",
      ["User.Drawings", "B.Cu", "B.Paste", "B.Mask", "Edge.Cuts"],
      "BOT Copper", (0.31, 0.49, 0.75))
    self.pdf_page("desc",
      ["User.Drawings", "F.SilkS", "B.SilkS", "Edge.Cuts"],
      "Descriptions", (0.95, 0.92, 0.63), drill=False)
    pdf_name = f"./{self.name}-layout.pdf"
    try:
      from ..mf.pdf import pdf_merge
    except ImportError:
      raise ImportError("Install with: pip install xaeian[eda]")
    pdf_merge(self.pdf_pages, pdf_name)
    FILE.remove(self.pdf_pages)

  def cpl(
    self,
    blacklist:list[str] = ["CP", "TP"],
    rotation_refs:dict[int, list[str]] = {},
    dnp:list[str] = [],
    jlcpcb_format:bool = False,
  ):
    """Export component placement list (pick & place)."""
    pos_name = self.produce_path + self.name + "-pos-all.csv"
    KiCad._execute([
      "kicad-cli", "pcb", "export", "pos", self.pcb,
      "--output", pos_name,
      "--side", "both", "--format", "csv",
      "--units", "mm", "--use-drill-file-origin",
      "--exclude-dnp",
    ])
    rows = CSV.load(pos_name)
    # Reference must end with digit, not start with digit/+/-
    rows = where(rows, lambda r:
      re.search(r"\d$", str(r.get("Ref", ""))) is not None
    )
    rows = where(rows, lambda r:
      not re.match(r"^[\d\+\-]", str(r.get("Ref", "")))
    )
    if blacklist:
      pattern = re.compile(r"^(?:" + "|".join(blacklist) + ")")
      rows = where(rows, lambda r:
        not pattern.search(str(r.get("Ref", "")))
      )
    if dnp:
      dnp_set = set(dnp)
      rows = where(rows, lambda r: r.get("Ref") not in dnp_set)
    # Apply rotation corrections
    for rotation, refs in rotation_refs.items():
      ref_set = set(refs)
      for r in rows:
        if r.get("Ref") in ref_set:
          r["Rot"] = float(r.get("Rot", 0)) + rotation
    if jlcpcb_format:
      rows = exclude(rows, "Val", "Package")
      replace_values(rows, "Side", {"top": "T", "bottom": "B"})
      rows = rename(rows, {
        "Ref": "Designator", "PosX": "Mid X",
        "PosY": "Mid Y", "Rot": "Rotation", "Side": "Layer",
      })
      rows = select(rows,
        "Designator", "Mid X", "Mid Y", "Layer", "Rotation",
      )
    suffix = ("-jlcpcb" if jlcpcb_format else "") + "-cpl"
    path = self.produce_path + self.name + suffix + ".csv"
    CSV.save(path, rows)
    FILE.remove(pos_name)

  def zip_prod(self, version:str=""):
    """ZIP entire produce folder."""
    if version: version = "-" + version
    DIR.zip(
      self.produce_path,
      self.produce_path + self.name + "-produce" + version + ".zip",
    )

  def pdf_schema(self):
    """Export schematic as PDF."""
    pdf_name = "./" + self.name + "-schema.pdf"
    KiCad._execute([
      "kicad-cli", "sch", "export", "pdf",
      self.sch, "--output", pdf_name,
    ])

  def ok(self):
    """Print success message."""
    folder = f"{c.ORANGE}{self.produce_path.removesuffix('/')}{c.END}"
    p.ok(f"Production files generated in {folder}")