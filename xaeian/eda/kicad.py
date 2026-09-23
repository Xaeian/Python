# xaeian/eda/kicad.py

"""
KiCad production file generator.

Automates BOM, gerber, CPL and PDF layout export via `kicad-cli`.

Footprint names may be given with or without the library prefix:
'Inductor:Coil-12x5mm' and 'Coil-12x5mm' select the same components.
Refs accept glob patterns - 'CN*', 'R?', 'IC[12]'.

Example:
  >>> from xaeian.eda.kicad import KiCad
  >>> kc = KiCad("./", "./produce")
  >>> kc.bom("JLCPCB", dnp_ref=["CN*"], dnp_package=["TO220-3"])
  >>> kc.gerber()
  >>> kc.cpl(jlcpcb_format=True, rot_package={"SOT23-3": 180})
  >>> kc.pdf_layout(el="both", cu="both", desc="top")
  >>> kc.zip_prod("v1.0")
  >>> kc.ok()
"""

import re, os, shutil
_HINT = "Install with: pip install xaeian[eda]"

from ..extras import MissingExtra, absent

try:
  from sexpdata import loads
except ModuleNotFoundError as e:
  if not absent(e, "sexpdata"): raise
  raise MissingExtra(_HINT) from e

from fnmatch import fnmatch
from typing import Any, Literal
from ..files import FILE, DIR, CSV, PATH
from ..colors import Color as c
from ..log import Logger, Print
from ..cmd import run as cmd_run
from ..table import (
  where, select, exclude, rename, add_column,
  set_defaults, aggregate, replace_values,
)

RENDER_COLORS = { # mask, silk, copper finish
  "green": ("#205F3ACC", "White", "ENIG"),
  "red": ("#7E2424D9", "White", "ENIG"),
  "blue": ("#1E4778D9", "White", "ENIG"),
  "yellow": ("#C49A24CC", "White", "ENIG"),
  "white": ("#EDEEECFF", "#000000", "HAL lead-free"),
  "black": ("#181818E6", "White", "ENIG"),
  "purple": ("#43236ED9", "White", "ENIG"),
}
RenderColor = Literal["green", "red", "blue", "yellow", "white", "black", "purple"]
Side = Literal[False, "top", "bot", "both"]

def load_netlist(path:str) -> list[dict[str, Any]]:
  """
  Parse a KiCad `.net` netlist into one dict per component.

  Keys are BOM column names, not netlist tags: `ref` → `Reference`, `footprint` → `Package`.
  Custom schematic properties become columns of their own, the `dnp` property becomes `DNP`,
  and the ordering fields are filled with empty defaults so every dict has the same keys.
  """
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

def _fix_path(path:str) -> str:
  return path.replace("\\", "/").removesuffix("/") + "/"

def _as_names(src, name:str) -> list[str]:
  """Flatten a str or any nested list/tuple/set of str. Tolerates a stray trailing comma."""
  if isinstance(src, str): return [src]
  if not isinstance(src, (list, tuple, set)):
    raise TypeError(f"{name}: expected str or list of str, got "
      f"{type(src).__name__}")
  out = []
  for x in src: out += _as_names(x, name)
  return out

def _as_parts(src, name:str) -> list:
  """Flatten a code str or `(manufacturer, code)`: tuples are parts, lists/sets containers."""
  if isinstance(src, str): return [src]
  if isinstance(src, tuple) and len(src) == 2 \
    and all(isinstance(i, str) for i in src): return [src]
  if not isinstance(src, (list, tuple, set)):
    raise TypeError(f"{name}: expected str or (manufacturer, code), got "
      f"{type(src).__name__}")
  out = []
  for x in src: out += _as_parts(x, name)
  return out

def _as_dict(src, name:str) -> dict:
  """Unwrap a dict left inside a one-element container (trailing comma)."""
  while not isinstance(src, dict):
    if not (isinstance(src, (list, tuple, set)) and len(src) == 1):
      raise TypeError(f"{name}: expected dict, got {type(src).__name__}")
    src = next(iter(src))
  return src

def _filter_dnp(rows:list[dict], dnp:list[str], ref_field:str="Reference") -> list[dict]:
  """Drop `dnp` refs; handles single and comma-joined ref cells, recomputes `Count`."""
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

def _merge_rows(rows:list[dict]) -> list[dict]:
  """Merge BOM rows that ended up sharing `(Manufacturer, Code)`."""
  out, index = [], {}
  for r in rows:
    key = (r.get("Manufacturer", ""), r.get("Code", ""))
    first = index.get(key)
    if first is None:
      index[key] = r
      out.append(r)
      continue
    first["Count"] = int(first.get("Count", 0)) + int(r.get("Count", 0))
    refs = [str(first.get("Reference", "")), str(r.get("Reference", ""))]
    first["Reference"] = ",".join(x for x in refs if x)
  return out

def _pkg_match(pkg:str, rows:list[dict]) -> list[dict]:
  """
  Rows whose `Package` matches: exact name first, then case-insensitive substring.

  Library prefix is optional on both sides - the netlist keeps it, `pcb export pos` drops it.
  """
  def norm(x) -> str: return str(x).rsplit(":", 1)[-1].strip().lower()
  key = norm(pkg)
  hit = [r for r in rows if norm(r.get("Package", "")) == key]
  if hit: return hit
  return [r for r in rows if key in norm(r.get("Package", ""))]

def _expand(src:dict) -> dict[str, float]:
  """Flatten `{key | tuple_of_keys: deg}` into `{key: deg}`."""
  out = {}
  for key, deg in src.items():
    for k in ((key,) if isinstance(key, str) else key):
      out[str(k).strip()] = float(deg)
  return out

def _inner_layers(pcb:str) -> list[str]:
  """`In1.Cu`, `In2.Cu`, ... declared in the board's `(layers ...)` block, in stack order."""
  with open(pcb, "r", encoding="utf-8") as f: src = f.read()
  head = src.split("(layers", 1)[-1].split("(setup", 1)[0]
  nums = sorted(int(n) for n in re.findall(r'\(\d+ "In(\d+)\.Cu"', head))
  return [f"In{n}.Cu" for n in nums]

def _patch_pcb_color(
  pcb:str, mask:str, silk:str, finish:str = "ENIG", inner:list[str]|None = None,
) -> str:
  """
  Write temp `.kicad_pcb` with stackup colors + full plot layers, caller removes it.

  `kicad-cli pcb render` always takes colors from the board stackup,
  and it paints the copper finish under the mask too.
  A light mask therefore needs full alpha and a neutral finish, otherwise gold bleeds through.
  The sibling `.kicad_pro` is copied alongside so the temp board keeps the project settings.
  """
  with open(pcb, "r", encoding="utf-8") as f: src = f.read()
  src = re.sub(
    r"\(layerselection 0x[0-9a-f_]+\)",
    "(layerselection 0x00000000_00000000_55555555_5755f5ff)", src, count=1,
  )
  layers = [
    ("F.Mask", "Top Solder Mask", mask),
    ("B.Mask", "Bottom Solder Mask", mask),
    ("F.SilkS", "Top Silk Screen", silk),
    ("B.SilkS", "Bottom Silk Screen", silk),
  ]
  if "(stackup" in src:
    for ly, ty, col in layers:
      head = rf'(\(layer "{ly}"\s*\(type "{ty}"\))'
      with_col = head + r'\s*\(color "[^"]*"\)'
      if re.search(with_col, src):
        src = re.sub(with_col, rf'\1\n\t\t\t(color "{col}")', src, count=1)
      else:
        src = re.sub(head, rf'\1\n\t\t\t(color "{col}")', src, count=1)
    src = re.sub(
      r'\(copper_finish "[^"]*"\)', f'(copper_finish "{finish}")',
      src, count=1,
    )
  else:
    copper = ["F.Cu", *(inner or []), "B.Cu"]
    core = round(1.51 / (len(copper) - 1), 3) # dielectric split evenly, the board stays 1.6 mm
    lines = [
      '(stackup',
      f'\t(layer "F.SilkS" (type "Top Silk Screen") (color "{silk}"))',
      '\t(layer "F.Paste" (type "Top Solder Paste"))',
      f'\t(layer "F.Mask" (type "Top Solder Mask") (color "{mask}") (thickness 0.01))',
    ]
    for i, cu in enumerate(copper):
      if i:
        lines.append(f'\t(layer "dielectric {i}" (type "core") (thickness {core})'
          ' (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))')
      lines.append(f'\t(layer "{cu}" (type "copper") (thickness 0.035))')
    lines += [
      f'\t(layer "B.Mask" (type "Bottom Solder Mask") (color "{mask}") (thickness 0.01))',
      '\t(layer "B.Paste" (type "Bottom Solder Paste"))',
      f'\t(layer "B.SilkS" (type "Bottom Silk Screen") (color "{silk}"))',
      f'\t(copper_finish "{finish}")',
      '\t(dielectric_constraints no)',
      ')',
    ]
    block = "".join(f"\t\t{line}\n" for line in lines)
    src = re.sub(r'(\(setup\s*\n)', rf'\1{block}', src, count=1)
  tmp = pcb.removesuffix(".kicad_pcb") + ".color.kicad_pcb"
  with open(tmp, "w", encoding="utf-8") as f: f.write(src)
  pro_src = pcb.removesuffix(".kicad_pcb") + ".kicad_pro"
  if os.path.exists(pro_src):
    shutil.copy(pro_src, tmp.removesuffix(".kicad_pcb") + ".kicad_pro")
  return tmp

PDF_PAGES = { # (kind, side): layers, title, color, drill
  ("el", "top"): (["User.Drawings", "F.Fab", "Edge.Cuts"],
    "TOP Component", (0.69, 0.69, 0.69), True),
  ("el", "bot"): (["User.Drawings", "B.Fab", "Edge.Cuts"],
    "BOT Component", (0.69, 0.69, 0.69), True),
  ("cu", "top"): (["User.Drawings", "F.Cu", "F.Paste", "F.Mask", "Edge.Cuts"],
    "TOP Copper", (0.79, 0.20, 0.20), True),
  ("cu", "bot"): (["User.Drawings", "B.Cu", "B.Paste", "B.Mask", "Edge.Cuts"],
    "BOT Copper", (0.31, 0.49, 0.75), True),
  ("desc", "top"): (["User.Drawings", "F.SilkS", "Edge.Cuts"],
    "TOP Descriptions", (0.95, 0.92, 0.63), False),
  ("desc", "bot"): (["User.Drawings", "B.SilkS", "Edge.Cuts"],
    "BOT Descriptions", (0.91, 0.69, 0.65), False),
}
INNER_COLORS = [ # KiCad default theme for In1.Cu, In2.Cu, ... as RGB 0-1
  (0.50, 0.78, 0.50),
  (0.81, 0.49, 0.17),
  (0.31, 0.80, 0.80),
  (0.86, 0.38, 0.55),
]
INNER_GRAY = (0.69, 0.69, 0.69) # past the table

#-------------------------------------------------------------------------------------- KiCad class

class KiCad:
  """Handle for one KiCad project; exports go to `produce_path`, PDFs to the working directory."""

  def _execute(self, args:list[str]):
    """Run a `kicad-cli` command; a non-zero exit logs stderr and raises `RuntimeError`."""
    result = cmd_run(args)
    if result.returncode:
      for line in result.stderr.strip().splitlines():
        if line: self.log.err(line)
      raise RuntimeError(f"kicad-cli failed: {' '.join(args[1:3])}")
    for line in result.stdout.strip().splitlines():
      if line: self.log.inf(line)

  def _match_refs(self, patterns:list[str], known:set[str], ctx:str) -> list[str]:
    """
    Expand glob ref patterns against `known`, case-insensitive.

    A selector that hits nothing warns and contributes nothing, glob and plain ref alike;
    an empty `known` universe lets plain refs through unchecked.
    """
    out = []
    for ref in patterns:
      if any(ch in ref for ch in "*?["):
        hit = sorted(x for x in known if fnmatch(x.lower(), ref.lower()))
      else:
        hit = [ref] if not known or ref in known else []
      if not hit: self.log.wrn(f"{ctx}: no ref matches '{ref}'")
      out += hit
    return out

  def _replace_parts(self, rows:list[dict], src:dict) -> list[dict]:
    """
    Swap parts for substitutes, merging rows that become identical.

    Key is a `code` or a `(manufacturer, code)` tuple, which wins over a bare `code`.
    `Reference` and `Count` come from the board and are never overwritten.
    """
    if not src: return rows
    plans = []
    for key, new in src.items():
      if not isinstance(new, dict):
        raise TypeError(f"replace['{key}']: expected dict of fields")
      new = {k: v for k, v in new.items() if k not in ("Reference", "Count")}
      if isinstance(key, str):
        plans.append((None, key.strip().lower(), new, key))
      else:
        plans.append((key[0].strip().lower(), key[1].strip().lower(), new, key))
    plans.sort(key=lambda x: x[0] is None) # exact (manufacturer, code) first
    used = set()
    for r in rows:
      man = str(r.get("Manufacturer", "")).strip().lower()
      code = str(r.get("Code", "")).strip().lower()
      for pman, pcode, new, key in plans:
        if pcode != code: continue
        if pman is not None and pman != man: continue
        r.update(new)
        used.add(str(key))
        break
    for _, _, _, key in plans:
      if str(key) not in used: self.log.wrn(f"Replace: no part '{key}' in the BOM")
    if used: self.log.inf(f"Replace: {len(used)} parts swapped")
    return _merge_rows(rows)

  def __init__(
    self,
    project_path:str = "./",
    produce_path:str = "./produce",
    log:Logger|Print|None = None,
  ) -> None:
    """
    Open a project: `name` is the stem of the first `.kicad_pcb`, else of the first `.kicad_sch`.

    `log` defaults to a fresh `Print`: this is a production tool and narrates what it does.

    A schematic makes this call run `kicad-cli` right away,
    exporting the netlist to fill `components` and `rows`.
    The export methods only reuse what is collected here.
    """
    self.log = log or Print()
    self.project_path:str = _fix_path(project_path)
    self.produce_path:str = _fix_path(produce_path)
    DIR.ensure(self.produce_path)
    pcb_files = DIR.file_list(
      self.project_path, exts=[".kicad_pcb"], shape="name",
    )
    sch_files = DIR.file_list(
      self.project_path, exts=[".kicad_sch"], shape="name",
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
    self.inner_cu:list[str] = _inner_layers(self.pcb) if self.has_pcb else []
    if self.inner_cu: self.log.inf(f"Board: {len(self.inner_cu) + 2} copper layers")
    self.components:list[dict] = [] # raw netlist, one entry per ref
    self.rows:list[dict] = [] # BOM, aggregated by `Manufacturer`+`Code`
    self.pdf_pages:list[str] = []
    if self.has_sch:
      self._load_bom()

  def _load_bom(self):
    """
    Export netlist, keep raw components and build aggregated BOM rows.

    `rows` drops what cannot be ordered - no `Code` (or `Code` of '-') and DNP parts -
    then aggregates by `Manufacturer`+`Code`. `components` keeps everything.
    """
    net_name = self.project_path + self.name + ".net"
    self._execute([
      "kicad-cli", "sch", "export", "netlist",
      self.sch, "--output", net_name,
    ])
    self.components = load_netlist(net_name)
    rows = where(self.components, lambda r:
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
    """Write one export CSV; no rows removes it, so a previous revision's file cannot ship."""
    if suffix: suffix = f"-{suffix}"
    path = self.produce_path + self.name + suffix + ".csv"
    if rows: CSV.save(path, rows)
    else: FILE.remove(path)

  def refs(self, manufacturer:str="", code:str="", package:str="") -> list[str]:
    """
    List refs of netlist components matching every given field.

    `manufacturer` and `code` are exact, empty matches any; `package` prefix is optional.
    Refs come straight from the netlist - DNP parts and parts without `Code` included.
    Giving no field at all raises, it would otherwise select the whole board.
    """
    if not (manufacturer or code or package):
      raise ValueError("refs: give at least one of manufacturer/code/package")
    rows = _pkg_match(package, self.components) if package else self.components
    man, code = manufacturer.strip().lower(), code.strip().lower()
    out = []
    for r in rows:
      if code and str(r.get("Code", "")).strip().lower() != code: continue
      if man and str(r.get("Manufacturer", "")).strip().lower() != man: continue
      ref = str(r.get("Reference", "")).strip()
      if ref: out.append(ref)
    return out

  def _rot_by_part(self, src:dict) -> dict[str, float]:
    """Resolve `{code | (manufacturer, code): deg}` into `{ref: deg}`."""
    out = {}
    for key, deg in src.items():
      man, code = ("", key) if isinstance(key, str) else key
      hit = self.refs(man, code)
      if not hit: self.log.wrn(f"Rotation: no part '{key}' on the board")
      for ref in hit: out[ref] = float(deg)
    return out

  def _rot_by_package(self, rows:list[dict], src:dict) -> dict[str, float]:
    """Resolve `{package | tuple_of_packages: deg}` into `{ref: deg}`."""
    out = {}
    for pkg, deg in _expand(src).items():
      hit = _pkg_match(pkg, rows)
      if not hit: self.log.wrn(f"Rotation: no footprint '{pkg}' in the CPL")
      for r in hit: out[str(r.get("Ref", "")).strip()] = float(deg)
    return out

  def _dnp_refs(self, refs, parts, packages, known:set[str]|None=None) -> list[str]:
    """
    Resolve ref/part/package DNP selectors into a flat ref list.

    Part and package lookups go through the netlist, so both need a schematic.
    `known` is the ref universe for glob expansion, defaults to the netlist.
    """
    refs = _as_names(refs or [], "dnp_ref")
    parts = _as_parts(parts or [], "dnp_part")
    packages = _as_names(packages or [], "dnp_package")
    if known is None:
      known = {str(r.get("Reference", "")).strip() for r in self.components}
    out = self._match_refs(refs, known, "DNP")
    for key in parts:
      man, code = ("", key) if isinstance(key, str) else key
      hit = self.refs(man, code)
      if not hit: self.log.wrn(f"DNP: no part '{key}' on the board")
      out += hit
    for pkg in packages:
      hit = self.refs(package=pkg)
      if not hit: self.log.wrn(f"DNP: no footprint '{pkg}' on the board")
      out += hit
    return out

  def bom(
    self,
    contractor:Literal["", "JLCPCB", "EuroCircuits"] = "",
    suffix:str = "",
    dnp_ref:list[str]|None = None,
    dnp_part:list|None = None,
    dnp_package:list[str]|None = None,
    replace:dict|None = None,
  ) -> None:
    """
    Generate BOM CSV, optionally formatted for a contractor.

    `GPN` set and not '-' overrides `Code` in the Eurocircuits BOM.
    In the general BOM it becomes a trailing column whenever any row carries it.
    Depopulation is per-production, the component stays populated in KiCad:
      `dnp_ref`: `["R17", "IC4"]`, glob allowed: `["CN*"]`
      `dnp_part`: `["LM2596S-5.0"]`, `[("TI", "SN74...")]`
      `dnp_package`: `["TO220-3"]`, library prefix optional
    `replace`: `{code | (manufacturer, code): {field: value}}`,
    any field except `Reference` and `Count`.
    """
    if not self.rows:
      self.log.wrn("BOM skipped: no schematic in the project")
      return
    tag = re.sub(r"[^a-z0-9]", "", contractor.lower())
    # copy: replacements edit rows in place, `self.rows` has to survive for the next call
    rows = [dict(r) for r in self.rows]
    dnp = set(self._dnp_refs(dnp_ref, dnp_part, dnp_package))
    rows = _filter_dnp(rows, list(dnp), ref_field="Reference")
    if not rows:
      self.log.wrn("BOM skipped: every component was depopulated")
      return
    rows = self._replace_parts(rows, _as_dict(replace or {}, "replace"))
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
          r["Manufacturer"] = "" # GPN: empty per Eurocircuits convention
      rows = select(rows,
        "Count", "Reference", "Code", "Manufacturer",
        "Value", "Package", "Description",
      )
      rows = rename(rows, {"Code": "MPN"})
      if not suffix: suffix = "eurocir-bom"
    else:
      has_lcsc = any(str(r.get("LCSC", "")).strip() for r in rows)
      has_gpn = any(str(r.get("GPN", "")).strip() not in ("", "-") for r in rows)
      cols = [
        "Manufacturer", "Code", "Value", "Package",
        "Description", "Count", "Datasheet", "Reference",
      ]
      if has_lcsc: cols.append("LCSC")
      if has_gpn: cols.append("GPN")
      rows = select(rows, *cols)
      if not suffix: suffix = "bom"
    self._save_csv(rows, suffix)
    note = f", {len(dnp)} refs depopulated" if dnp else ""
    self.log.inf(f"BOM ready: {len(rows)} lines{note}")

  def gerber(self) -> None:
    """Export gerber + drill files and package as ZIP."""
    if not self.has_pcb:
      self.log.wrn("Gerber skipped: no PCB in the project")
      return
    gerbers_path = self.produce_path + "gerber"
    layers = ["F.Cu", *self.inner_cu, "B.Cu",
      "F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "F.Mask", "B.Mask", "Edge.Cuts"]
    self._execute([
      "kicad-cli", "pcb", "export", "gerbers", self.pcb,
      "--output", gerbers_path,
      "--layers", ",".join(layers),
      "--sdnp", "--subtract-soldermask",
      "--use-drill-file-origin", "--precision", "6",
    ])
    self._execute([
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

  def cpl(
    self,
    blacklist:list[str]|None = None,
    rot_ref:dict|None = None,
    rot_part:dict|None = None,
    rot_package:dict|None = None,
    dnp_ref:list[str]|None = None,
    dnp_part:list|None = None,
    dnp_package:list[str]|None = None,
    jlcpcb_format:bool = False,
    one_side:Literal[False, "top", "bot"] = False,
    suffix:str = "",
  ) -> None:
    """
    Export component placement list (pick & place).

    `blacklist` drops ref prefixes, `None` meaning the `CP`/`TP` default; `[]` keeps all.

    Rotations are corrections in degrees added to `Rot`, wrapped to 0..360.
    Priority: `rot_ref` > `rot_part` > `rot_package`.
      `rot_ref`: `{"IC4": 180}`, `{("IC4", "IC6"): 180}`, glob: `{"CN*": 90}`
      `rot_part`: `{"SN74LVC1G14": 180}`, `{("TI", "SN74..."): 180}`
      `rot_package`: `{"SOT23-3": 180}`, `{("SOT23-3", "SOD-123"): 90}`
    Depopulation selectors mirror `bom()` and run before rotation,
    so a footprint listed in both is already gone by the time rotations apply.
    Everything except `rot_package` resolves through the netlist and needs a schematic.
    Empty `suffix` becomes `jlcpcb-cpl` or `cpl`. Side is never auto-appended,
    so pass e.g. `suffix="cpl-top"` to keep both sides apart.
    """
    if not self.has_pcb:
      self.log.wrn("CPL skipped: no PCB in the project")
      return
    if blacklist is None: blacklist = ["CP", "TP"] # test points and caps ship unplaced
    rot_ref = _as_dict(rot_ref or {}, "rot_ref")
    rot_part = _as_dict(rot_part or {}, "rot_part")
    rot_package = _as_dict(rot_package or {}, "rot_package")
    pos_name = self.produce_path + self.name + "-pos-all.csv"
    self._execute([
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
    known = {str(r.get("Reference", "")).strip() for r in self.components} \
      | {str(r.get("Ref", "")).strip() for r in rows}
    dnp = set(self._dnp_refs(dnp_ref, dnp_part, dnp_package, known))
    rows = _filter_dnp(rows, list(dnp), ref_field="Ref")
    on_board = {str(r.get("Ref", "")).strip() for r in rows} # before side split
    if one_side:
      side_full = "top" if one_side == "top" else "bottom"
      rows = where(rows, lambda r:
        str(r.get("Side", "")).lower() == side_full
      )
    explicit = {}
    for key, deg in _expand(rot_ref).items():
      for ref in self._match_refs([key], on_board, "Rotation"):
        explicit[ref] = deg
    rot = self._rot_by_package(rows, rot_package)
    rot |= self._rot_by_part(rot_part) # merge order sets priority
    rot |= explicit
    turned = 0
    for r in rows:
      deg = rot.get(str(r.get("Ref", "")).strip())
      if deg is not None:
        r["Rot"] = round((float(r.get("Rot", 0)) + deg) % 360, 3)
        turned += 1
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
    self._save_csv(rows, suffix)
    FILE.remove(pos_name)
    if not rows:
      self.log.wrn("CPL skipped: nothing left after filters")
      return
    note = f", {len(dnp)} refs depopulated" if dnp else ""
    self.log.inf(f"CPL ready: {len(rows)} components, {turned} rotated{note}")

  def pdf_page(
    self,
    name:str,
    layers:list[str],
    desc:str = "",
    desc_color:tuple = (0, 0, 0),
    drill:bool = True,
  ) -> None:
    """
    Export single PDF page from PCB layers and queue it in `pdf_pages`.

    `pdf_layout()` merges the queue then deletes the parts. `desc` is stamped onto the page,
    `desc_color` is RGB 0-1.
    """
    pdf_name = f"./{self.name}-{name}.pdf"
    self._execute([
      "kicad-cli", "pcb", "export", "pdf", self.pcb,
      "--output", pdf_name,
      "--layers", ",".join(layers),
      "--subtract-soldermask",
      "--drill-shape-opt", "2" if drill else "0",
      "--include-border-title",
    ])
    if desc:
      from ..media.pdf import pdf_add_text # raises MissingExtra naming its own extra
      pdf_add_text(
        pdf_name, pdf_name, desc,
        (33, 20), "cobo", 10, desc_color, inplace=True,
      )
    self.pdf_pages.append(pdf_name)

  def pdf_layout(self, el:Side="top", cu:Side="both", desc:Side="top") -> None:
    """
    Generate multi-page PCB layout PDF, one page per kind and side.

    Each argument selects the sides to emit, `False` skips the kind entirely.
    `el`: fabrication outlines with component refs
    `cu`: copper with paste and mask; `"both"` on a multilayer board adds
    one page per inner copper layer between top and bot
    `desc`: silkscreen only, no drill marks
    """
    if not self.has_pcb:
      self.log.wrn("Layout PDF skipped: no PCB in the project")
      return
    self.pdf_pages = []
    def sides(v:Side) -> tuple[str, ...]:
      return ("top", "bot") if v == "both" else ((v,) if v else ())
    for kind, value in (("el", el), ("cu", cu), ("desc", desc)):
      for side in sides(value):
        layers, title, col, drill = PDF_PAGES[(kind, side)]
        self.pdf_page(f"{kind}-{side}", layers, title, col, drill)
        if kind == "cu" and side == "top" and value == "both": self._pdf_inner_pages()
    if not self.pdf_pages:
      self.log.wrn("Layout PDF skipped: no pages selected")
      return
    pdf_name = f"./{self.name}-layout.pdf"
    from ..media.pdf import pdf_merge # raises MissingExtra naming its own extra
    pdf_merge(self.pdf_pages, pdf_name)
    FILE.remove(self.pdf_pages)

  def _pdf_inner_pages(self) -> None:
    """One copper page per inner layer, between the top and bottom copper pages."""
    for i, cu in enumerate(self.inner_cu):
      name = cu.removesuffix(".Cu")
      col = INNER_COLORS[i] if i < len(INNER_COLORS) else INNER_GRAY
      self.pdf_page(f"cu-{name.lower()}", ["User.Drawings", cu, "Edge.Cuts"],
        f"{name.upper()} Copper", col, True)

  def pdf_schema(self) -> None:
    """Export schematic as PDF."""
    if not self.has_sch:
      self.log.wrn("Schema PDF skipped: no schematic in the project")
      return
    pdf_name = f"./{self.name}-schema.pdf"
    self._execute([
      "kicad-cli", "sch", "export", "pdf",
      self.sch, "--output", pdf_name,
    ])

  def view(
    self,
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
  ) -> None:
    """
    Render 3D raytraced image of PCB. `color=None` → original PCB untouched.

    Any other `color` renders from a temp recolored copy of the board, removed afterwards.
    `pan` is `(x, y, z)`, `width` and `height` are pixels.
    """
    if not self.has_pcb:
      self.log.wrn("3D render skipped: no PCB in the project")
      return
    pcb = self.pcb
    tmp = None
    if color:
      mask, silk, finish = RENDER_COLORS[color]
      pcb = tmp = _patch_pcb_color(self.pcb, mask, silk, finish, self.inner_cu)
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
    try: self._execute(args)
    finally:
      if tmp:
        FILE.remove(tmp)
        pro_tmp = tmp.removesuffix(".kicad_pcb") + ".kicad_pro"
        if os.path.exists(pro_tmp): FILE.remove(pro_tmp)

  def zip_prod(self, version:str="") -> None:
    """ZIP entire produce folder, so call it after every other export."""
    if version: version = "-" + version
    DIR.zip(
      self.produce_path,
      self.produce_path + self.name + "-produce" + version + ".zip",
    )

  def ok(self) -> None:
    """Print where the production files landed."""
    folder = f"{c.ORANGE}{self.produce_path.removesuffix('/')}{c.END}"
    self.log.ok(f"Production files generated in {folder}")