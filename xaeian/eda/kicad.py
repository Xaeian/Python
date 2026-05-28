# xaeian/eda/kicad.py

"""
KiCad production file generator.

Automates BOM, gerber, CPL and PDF layout export via `kicad-cli`.

Example:
  >>> from xaeian.eda.kicad import KiCad
  >>> kc = KiCad("./", "./produce")
  >>> kc.bom()
  >>> kc.bom("JLCPCB")
  >>> kc.bom("EuroCircuits")
  >>> kc.gerber()
  >>> kc.cpl(jlcpcb_format=True)
  >>> kc.cpl(one_side="top", suffix="cpl-top")
  >>> kc.pdf_layout()
  >>> kc.pdf_schema()
  >>> kc.zip_prod("v1.0")
  >>> kc.ok()
"""

import sys, re, os, shutil
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

RENDER_COLORS = {
  "green":  ("#205F3ACC", "White"),
  "red":    ("#7E2424D9", "White"),
  "blue":   ("#1E4778D9", "White"),
  "yellow": ("#C49A24CC", "#000000"),
  "white":  ("#E8DFD0E6", "#000000"),
  "black":  ("#181818E6", "White"),
  "purple": ("#43236ED9", "White"),
}
RenderColor = Literal["green","red","blue","yellow","white","black","purple"]

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
          elif _tagged(el, "footprint"): d["Package"] = el[1]
          elif _tagged(el, "datasheet"): d["Datasheet"] = el[1]
          elif _tagged(el, "description"): d["Description"] = el[1]
          elif _tagged(el, "property") and len(el) >= 2:
            name, value = None, None
            if isinstance(el[1], str):
              name = el[1]
              if len(el) >= 3 and isinstance(el[2], str):
                value = el[2]
            else:
              for sub in el[1:]:
                if _tagged(sub, "name"): name = sub[1]
                elif _tagged(sub, "value"): value = sub[1]
            if name == "dnp":
              d["DNP"] = True
            elif name and value:
              d[str(name)] = value
        set_defaults([d],
          DNP=False, Count=1, Datasheet="",
          Manufacturer="", Code="", GPN="",
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
        if line: p.err(line)
      sys.exit(1)
    for line in result.stdout.strip().splitlines():
      if line: p.inf(line)

  @staticmethod
  def _filter_dnp(
    rows:list[dict], dnp:list[str], ref_field:str = "Reference",
  ) -> list[dict]:
    """Remove refs listed in `dnp` from `rows`. Handles both CPL rows
    (single ref) and aggregated BOM rows (comma-joined refs).
    Recomputes `Count` if present. Preserves original ref separator.
    """
    if not dnp: return rows
    dnp_set = set(dnp)
    result = []
    for r in rows:
      raw = str(r.get(ref_field, "")).strip()
      sep = ", " if ", " in raw else ","
      refs = [x.strip() for x in raw.split(",") if x.strip()]
      kept = [x for x in refs if x not in dnp_set]
      if not kept: continue
      r = dict(r)
      r[ref_field] = sep.join(kept)
      if "Count" in r: r["Count"] = len(kept)
      result.append(r)
    return result

  @staticmethod
  def _patch_pcb_color(pcb:str, mask:str, silk:str) -> str:
    """Write temp `.kicad_pcb` with stackup colors + full plot layers. Return temp path."""
    with open(pcb, "r", encoding="utf-8") as f: c = f.read()
    c = re.sub(
      r"\(layerselection 0x[0-9a-f_]+\)",
      "(layerselection 0x00000000_00000000_55555555_5755f5ff)", c, count=1,
    )
    layers = [
      ("F.Mask",  "Top Solder Mask",    mask),
      ("B.Mask",  "Bottom Solder Mask", mask),
      ("F.SilkS", "Top Silk Screen",    silk),
      ("B.SilkS", "Bottom Silk Screen", silk),
    ]
    if "(stackup" in c:
      for ly, ty, col in layers:
        head = rf'(\(layer "{ly}"\s*\(type "{ty}"\))'
        with_col = head + r'\s*\(color "[^"]*"\)'
        if re.search(with_col, c):
          c = re.sub(with_col, rf'\1\n\t\t\t(color "{col}")', c, count=1)
        else:
          c = re.sub(head, rf'\1\n\t\t\t(color "{col}")', c, count=1)
      c = re.sub(r'\(copper_finish "[^"]*"\)', '(copper_finish "ENIG")', c, count=1)
    else:
      block = (
        '\t\t(stackup\n'
        f'\t\t\t(layer "F.SilkS" (type "Top Silk Screen") (color "{silk}"))\n'
        '\t\t\t(layer "F.Paste" (type "Top Solder Paste"))\n'
        f'\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "{mask}") (thickness 0.01))\n'
        '\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n'
        '\t\t\t(layer "dielectric 1" (type "core") (thickness 1.51)'
        ' (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))\n'
        '\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))\n'
        f'\t\t\t(layer "B.Mask" (type "Bottom Solder Mask")'
        f' (color "{mask}") (thickness 0.01))\n'
        '\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))\n'
        f'\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen") (color "{silk}"))\n'
        '\t\t\t(copper_finish "ENIG")\n\t\t\t(dielectric_constraints no)\n\t\t)\n'
      )
      c = re.sub(r'(\(setup\s*\n)', rf'\1{block}', c, count=1)
    tmp = pcb.removesuffix(".kicad_pcb") + ".color.kicad_pcb"
    with open(tmp, "w", encoding="utf-8") as f: f.write(c)
    pro_src = pcb.removesuffix(".kicad_pcb") + ".kicad_pro"
    if os.path.exists(pro_src):
      shutil.copy(pro_src, tmp.removesuffix(".kicad_pcb") + ".kicad_pro")
    return tmp

  def __init__(self, project_path:str="./", produce_path:str="./produce"):
    self.project_path:str = self._fix_path(project_path)
    self.produce_path:str = self._fix_path(produce_path)
    DIR.ensure(self.produce_path)
    pcb_files = DIR.file_list(
      self.project_path, exts=[".kicad_pcb"], basename=True,
    )
    sch_files = DIR.file_list(
      self.project_path, exts=[".kicad_sch"], basename=True,
    )
    if not pcb_files and not sch_files:
      raise FileNotFoundError(
        "No '.kicad_pcb' or '.kicad_sch' found in " + self.project_path
      )
    self.name:str = PATH.stem((pcb_files or sch_files)[0])
    self.pcb = self.project_path + self.name + ".kicad_pcb"
    self.sch = self.project_path + self.name + ".kicad_sch"
    self.has_pcb = bool(pcb_files)
    self.has_sch = bool(sch_files)
    self.rows:list[dict] = []
    if self.has_sch:
      self._load_bom()

  def _load_bom(self):
    """Export netlist and parse BOM rows."""
    net_name = self.project_path + self.name + ".net"
    KiCad._execute([
      "kicad-cli", "sch", "export", "netlist",
      self.sch, "--output", net_name,
    ])
    components = KiCad.load_netlist(net_name)
    rows = where(components, lambda r:
      str(r.get("Code", "")).strip().lower() not in ("", "-")
    )
    rows = where(rows, lambda r: not r.get("DNP", False))
    rows = exclude(rows, "DNP")
    self.rows = aggregate(rows, ["Manufacturer", "Code"], {
      "Value": "first", "Package": "first", "Description": "first",
      "GPN": "first",
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
    dnp:list[str] = [],
  ):
    """Generate BOM CSV, optionally formatted for a contractor.

    GPN field convention: if `GPN` is set and not '-', it overrides `Code`
    in Eurocircuits BOM (with `Manufacturer` cleared per their convention).
    For general BOM, GPN column is appended at the end when any row has it.
    `dnp`: per-production refs to exclude (component stays populated in KiCad).
    """
    if not self.rows:
      p.wrn("No schematic: skipping BOM")
      return
    tag = re.sub(r"[^a-z0-9]", "", contractor.lower())
    rows = [dict(r) for r in self.rows]  # shallow copy
    rows = KiCad._filter_dnp(rows, dnp, ref_field="Reference")
    if not rows:
      p.wrn("All BOM rows filtered out by DNP")
      return
    if tag == "jlcpcb":
      add_column(rows, "Comment", lambda r:
        f'{r["Manufacturer"]}; {r["Code"]}; {r["Description"]}'
      )
      rows = select(rows, "Comment", "Reference", "Package", "LCSC")
      rows = rename(rows, {
        "Reference": "Designator",
        "Package": "Footprint",
        "LCSC": "JLCPCB Part #",
      })
      if not suffix: suffix = "jlcpcb-bom"
    elif tag == "eurocircuits":
      for r in rows:
        gpn = str(r.get("GPN", "")).strip()
        if gpn and gpn != "-":
          r["Code"] = gpn
          r["Manufacturer"] = ""  # GPN: empty per Eurocircuits convention
      rows = select(rows,
        "Count", "Reference", "Code", "Manufacturer",
        "Value", "Package", "Description",
      )
      rows = rename(rows, {"Code": "MPN"})
      if not suffix: suffix = "eurocir-bom"
    else:
      has_lcsc = any(str(r.get("LCSC", "")).strip() for r in rows)
      has_gpn = any(
        str(r.get("GPN", "")).strip() not in ("", "-") for r in rows
      )
      cols = [
        "Manufacturer", "Code", "Value", "Package",
        "Description", "Count", "Datasheet", "Reference",
      ]
      if has_lcsc: cols.append("LCSC")
      if has_gpn: cols.append("GPN")
      rows = select(rows, *cols)
      if not suffix: suffix = "bom"
    self._save_csv(rows, suffix)

  def gerber(self):
    """Export gerber + drill files and package as ZIP."""
    if not self.has_pcb:
      p.wrn("No PCB file: skipping gerber")
      return
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
        from ..media.pdf import pdf_add_text
      except ImportError:
        raise ImportError("Install with: pip install xaeian[eda]")
      pdf_add_text(
        pdf_name, pdf_name, desc,
        (33, 20), "cobo", 10, desc_color, inplace=True,
      )
    self.pdf_pages.append(pdf_name)

  def pdf_layout(self, top:bool=True, bot:bool=False):
    """Generate multi-page PCB layout PDF."""
    if not self.has_pcb:
      p.wrn("No PCB file: skipping layout PDF")
      return
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
    if top:
      self.pdf_page("desc-top",
        ["User.Drawings", "F.SilkS", "Edge.Cuts"],
        "TOP Descriptions", (0.95, 0.92, 0.63), drill=False)
    if bot:
      self.pdf_page("desc-bot",
        ["User.Drawings", "B.SilkS", "Edge.Cuts"],
        "BOT Descriptions", (0.91, 0.69, 0.65), drill=False)
    pdf_name = f"./{self.name}-layout.pdf"
    try:
      from ..media.pdf import pdf_merge
    except ImportError:
      raise ImportError("Install with: pip install xaeian[eda]")
    pdf_merge(self.pdf_pages, pdf_name)
    FILE.remove(self.pdf_pages)

  def view(self,
    side:str = "top",
    color:RenderColor|None = None,
    width:int = 2000,
    height:int = 1500,
    quality:str = "high",
    background:str = "transparent",
    zoom:float|None = None,
    pan:tuple|None = None,
    perspective:bool = False,
    floor:bool = False,
  ):
    """Render 3D raytraced image of PCB. `color=None` -> original PCB untouched."""
    if not self.has_pcb:
      p.wrn("No PCB file: skipping 3D render")
      return
    pcb = self.pcb
    tmp = None
    if color:
      mask, silk = RENDER_COLORS[color]
      pcb = tmp = KiCad._patch_pcb_color(self.pcb, mask, silk)
    path = self.produce_path + self.name + f"-{side}.png"
    args = [
      "kicad-cli", "pcb", "render", pcb,
      f"--output={path}",
      f"--side={side}",
      f"--width={width}",
      f"--height={height}",
      f"--quality={quality}",
      f"--background={background}",
    ]
    if zoom: args.append(f"--zoom={zoom}")
    if pan: args.append(f"--pan='{pan[0]},{pan[1]},{pan[2]}'")
    if perspective: args.append("--perspective")
    if floor: args.append("--floor")
    try: KiCad._execute(args)
    finally:
      if tmp:
        FILE.remove(tmp)
        pro_tmp = tmp.removesuffix(".kicad_pcb") + ".kicad_pro"
        if os.path.exists(pro_tmp): FILE.remove(pro_tmp)

  def cpl(
    self,
    blacklist:list[str] = ["CP", "TP"],
    rotation_refs:dict[int, list[str]] = {},
    dnp:list[str] = [],
    jlcpcb_format:bool = False,
    one_side:Literal[False, "top", "bot"] = False,
    suffix:str = "",
  ):
    """Export component placement list (pick & place).

    `one_side`: if "top" or "bot", export only components on that side.
    `suffix`: override output filename suffix. If empty, defaults to
    `jlcpcb-cpl` (when `jlcpcb_format=True`) or `cpl`. Side is NOT
    auto-appended; pass e.g. `suffix="cpl-top"` to differentiate sides.
    """
    if not self.has_pcb:
      p.wrn("No PCB file: skipping CPL")
      return
    pos_name = self.produce_path + self.name + "-pos-all.csv"
    KiCad._execute([
      "kicad-cli", "pcb", "export", "pos", self.pcb,
      "--output", pos_name,
      "--side", "both", "--format", "csv",
      "--units", "mm", "--use-drill-file-origin",
      "--exclude-dnp",
    ])
    rows = CSV.load(pos_name)
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
    rows = KiCad._filter_dnp(rows, dnp, ref_field="Ref")
    if one_side:
      side_full = "top" if one_side == "top" else "bottom"
      rows = where(rows, lambda r:
        str(r.get("Side", "")).lower() == side_full
      )
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
    if not suffix:
      suffix = ("jlcpcb-" if jlcpcb_format else "") + "cpl"
    path = self.produce_path + self.name + "-" + suffix + ".csv"
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
    if not self.has_sch:
      p.wrn("No schematic: skipping schema PDF")
      return
    pdf_name = "./" + self.name + "-schema.pdf"
    KiCad._execute([
      "kicad-cli", "sch", "export", "pdf",
      self.sch, "--output", pdf_name,
    ])

  def ok(self):
    """Print success message."""
    folder = f"{c.ORANGE}{self.produce_path.removesuffix('/')}{c.END}"
    p.ok(f"Production files generated in {folder}")